/**
 * Pacific BioArchive — 全局配置示例（占位符版，可安全提交）
 * 真实部署时：复制本文件为 frontend/js/config.js 并填入真实值。
 * 真实 config.js 已被 .gitignore 忽略，避免把密钥/资源标识提交到仓库。
 */
window.APP_CONFIG = {
  /* ---- AWS 基础 ---- */
  region: 'YOUR_REGION',                 // 例如 us-east-1（与创建资源时一致）

  /* ---- Cognito ---- */
  cognitoClientId: 'YOUR_COGNITO_CLIENT_ID',
  cognitoClientSecret: '',               // Public(无 secret) 客户端留空即可
  cognitoUserPoolId: 'YOUR_COGNITO_USER_POOL_ID',

  /* ---- API Gateway ---- */
  apiBaseUrl: 'YOUR_UPLOAD_API_BASE_URL/',    // 成员 A 的上传 API（末尾带 /）
  queryApiBaseUrl: 'YOUR_QUERY_API_BASE_URL/',// 成员 C 的查询/通知 API（末尾带 /）

  /* ---- S3 ---- */
  bucketName: 'YOUR_S3_BUCKET',

  /* ---- 桶目录约定（三人契约，勿改）---- */
  paths: {
    uploads: 'uploads/',
    thumbnails: 'thumbnails/',
    models: 'models/'
  }
};