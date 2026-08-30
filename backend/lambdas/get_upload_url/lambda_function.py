"""
Pacific BioArchive — get-upload-url Lambda（成员 A）
功能：
  1. 去重：完整 checksum 的 DynamoDB GSI 查询 + 确定性 S3 Key 条件写入
  2. 生成 S3 presigned URL，供前端 PUT 直传（支持大文件视频）

部署：见 docs/AWS_SETUP_GUIDE.md Step 3-5
环境变量（Lambda 中配置）：
  BUCKET_NAME         S3 桶名（必填）
  FILES_TABLE         DynamoDB 表名（可选，B/C 创建后启用数据库层去重）
  CHECKSUM_INDEX      checksum 的 GSI 名（可选，未配置时降级为 Scan）
IAM 要求：s3:PutObject + s3:GetObject（uploads/*）+ dynamodb:Query（checksum-index）
"""
import json
import logging
import os
import re
from urllib.parse import quote, unquote

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
BUCKET = os.environ.get("BUCKET_NAME", "")           # TODO 占位：配置为实际桶名
FILES_TABLE = os.environ.get("FILES_TABLE", "")      # TODO 占位：B/C 的表建好后配置
CHECKSUM_INDEX = os.environ.get("CHECKSUM_INDEX", "")  # TODO 占位：如 GSI 名为 checksum-index
UPLOAD_PREFIX = os.environ.get("UPLOAD_PREFIX", "uploads/by-checksum/").strip("/") + "/"

s3 = boto3.client(
    "s3",
    region_name=REGION,
    config=Config(signature_version="s3v4"),
)
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
    """Query the full SHA-256 value through the checksum GSI."""
    if not checksum or not FILES_TABLE:
        return False
    if not CHECKSUM_INDEX:
        raise RuntimeError("CHECKSUM_INDEX must be configured when FILES_TABLE is set")
    table = dynamodb.Table(FILES_TABLE)
    resp = table.query(
        IndexName=CHECKSUM_INDEX,
        KeyConditionExpression=Key("checksum").eq(checksum),
        ProjectionExpression="file_id",
        Limit=1,
    )
    return bool(resp.get("Items"))


def _is_missing_object(exc):
    if not isinstance(exc, ClientError):
        return False
    error = exc.response.get("Error") or {}
    return str(error.get("Code", "")) in {"404", "NoSuchKey", "NotFound"}


def _object_exists(key):
    """Check the deterministic checksum object without listing the bucket."""
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except ClientError as exc:
        if _is_missing_object(exc):
            return False
        raise


def _safe_filename(raw_filename):
    value = unquote(raw_filename or "file").replace("\\", "/")
    return value.rsplit("/", 1)[-1].strip() or "file"


def _object_key(checksum):
    return f"{UPLOAD_PREFIX}{checksum}"


def _cognito_sub(event):
    """Support REST API Cognito authorizers and HTTP API JWT authorizers."""
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    claims = authorizer.get("claims") or (authorizer.get("jwt") or {}).get("claims") or {}
    return str(claims.get("sub") or "")


def lambda_handler(event, context):
    params = event.get("queryStringParameters") or {}
    filename = params.get("filename", "file")
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

    safe_name = _safe_filename(filename)
    file_key = _object_key(checksum)

    # 1. Full-checksum DB lookup covers completed records. The exact
    # deterministic S3 key covers new and in-flight records.
    try:
        duplicate = (
            _check_duplicate_db(checksum)
            or _object_exists(file_key)
        )
    except Exception:
        logger.exception("duplicate check failed for checksum=%s", checksum)
        return _json(503, {"error": "duplicate check is temporarily unavailable"})
    if duplicate:
        return _json(
            200,
            {
                "duplicate": True,
                "checksum": checksum,
                "message": "duplicate file (same checksum)",
            },
        )

    # 2. Sign a conditional write. The deterministic key makes identical
    # content converge on one object, and If-None-Match closes concurrent races.
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": BUCKET,
            "Key": file_key,
            "ContentType": content_type,
            "IfNoneMatch": "*",
            "Metadata": {
                "checksum": checksum,
                "uploaded-by": uploaded_by,
                "original-filename": quote(safe_name, safe=""),
            },
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
                "If-None-Match": "*",
                "x-amz-meta-checksum": checksum,
                "x-amz-meta-uploaded-by": uploaded_by,
                "x-amz-meta-original-filename": quote(safe_name, safe=""),
            },
            "duplicate": False,
        },
    )
