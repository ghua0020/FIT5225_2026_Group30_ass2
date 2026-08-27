"""
Pacific BioArchive — get-upload-url Lambda（成员 A）
功能：
  1. 去重：S3 前缀查找（立即可用）+ 可选 DynamoDB 查询（B/C 表就绪后自动叠加）
  2. 生成 S3 presigned URL，供前端 PUT 直传（支持大文件视频）

部署：见 docs/AWS_SETUP_GUIDE.md Step 3-5
环境变量（Lambda 中配置）：
  BUCKET_NAME         S3 桶名（必填）
  FILES_TABLE         DynamoDB 表名（可选，B/C 创建后启用数据库层去重）
  CHECKSUM_INDEX      checksum 的 GSI 名（可选，未配置时降级为 Scan）
IAM 要求：s3:PutObject + s3:GetObject（uploads/*）+ s3:ListBucket（桶级）
"""
import json
import logging
import os
import re
import uuid
from urllib.parse import unquote

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
BUCKET = os.environ.get("BUCKET_NAME", "")           # TODO 占位：配置为实际桶名
FILES_TABLE = os.environ.get("FILES_TABLE", "")      # TODO 占位：B/C 的表建好后配置
CHECKSUM_INDEX = os.environ.get("CHECKSUM_INDEX", "")  # TODO 占位：如 GSI 名为 checksum-index

s3 = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)


def _json(status, body):
    # Lambda Proxy 集成下，CORS 头必须由 Lambda 自己返回（API Gateway 不会自动添加）
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token",
            "Access-Control-Allow-Methods": "GET,PUT,POST,DELETE,OPTIONS",
        },
        "body": json.dumps(body),
    }


def _check_duplicate_db(checksum):
    """按 checksum 查 DynamoDB（B/C 的表建好并配置环境变量后生效）；
    表/索引不存在时记录日志并跳过，不阻塞上传。"""
    if not checksum or not FILES_TABLE:
        return False
    try:
        table = dynamodb.Table(FILES_TABLE)
        if CHECKSUM_INDEX:
            resp = table.query(
                IndexName=CHECKSUM_INDEX,
                KeyConditionExpression=boto3.dynamodb.conditions.Key("checksum").eq(checksum),
                Limit=1,
            )
        else:
            # 无 GSI 时降级为 Scan（测试数据量小可用，正式环境由 C 建 GSI）
            resp = table.scan(
                FilterExpression=boto3.dynamodb.conditions.Attr("checksum").eq(checksum),
                Limit=1,
            )
        return resp.get("Count", 0) > 0
    except Exception as e:
        logger.warning("db duplicate check skipped: %s", e)
        return False


def _check_duplicate_s3(checksum):
    """S3 层去重：对象 key 以 checksum 前缀命名，按前缀查找即可判断是否已存在。
    不依赖 DynamoDB，立即生效（需要 IAM 的 s3:ListBucket 权限）。"""
    if not checksum:
        return False
    try:
        resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=f"uploads/{checksum[:16]}", MaxKeys=1)
        return resp.get("KeyCount", 0) > 0
    except Exception as e:
        logger.warning("s3 duplicate check skipped: %s", e)
        return False


def _cognito_sub(event):
    """Support REST API Cognito authorizers and HTTP API JWT authorizers."""
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    claims = authorizer.get("claims") or (authorizer.get("jwt") or {}).get("claims") or {}
    return str(claims.get("sub") or "")


def lambda_handler(event, context):
    params = event.get("queryStringParameters") or {}
    filename = unquote(params.get("filename", "file"))
    content_type = params.get("content_type") or "application/octet-stream"
    checksum = (params.get("checksum") or "").strip()
    uploaded_by = _cognito_sub(event)

    if not BUCKET:
        return _json(500, {"error": "BUCKET_NAME not configured in Lambda env vars"})
    if not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
        return _json(400, {"error": "checksum must be a complete SHA-256 value"})
    if not uploaded_by:
        return _json(401, {"error": "authenticated Cognito sub is required"})
    checksum = checksum.lower()

    # 1. 去重检查：数据库（可选）或 S3 前缀查找，任一命中即判定重复
    if checksum and (_check_duplicate_db(checksum) or _check_duplicate_s3(checksum)):
        return _json(200, {"duplicate": True, "message": "duplicate file (same checksum)"})

    # 2. 生成对象 key：uploads/{checksum前16位}-{原始文件名}
    #    checksum 前缀用于 S3 层去重；未提供 checksum 时退回 uuid 命名
    safe_name = os.path.basename(filename) or "file"
    if checksum:
        file_key = f"uploads/{checksum[:16]}-{safe_name}"
    else:
        file_key = f"uploads/{uuid.uuid4().hex[:8]}-{safe_name}"

    # 3. 生成 presigned URL（5 分钟有效）
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": BUCKET,
            "Key": file_key,
            "ContentType": content_type,
            "Metadata": {"checksum": checksum, "uploaded-by": uploaded_by},
        },
        ExpiresIn=300,
    )

    logger.info("presigned url issued for %s (checksum=%s)", file_key, checksum or "-")
    return _json(
        200,
        {
            "uploadUrl": upload_url,
            "fileKey": file_key,
            "fileName": safe_name,
            "contentType": content_type,
            "uploadHeaders": {
                "Content-Type": content_type,
                "x-amz-meta-checksum": checksum,
                "x-amz-meta-uploaded-by": uploaded_by,
            },
            "duplicate": False,
        },
    )
