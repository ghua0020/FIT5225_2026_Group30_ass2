/**
 * Pacific BioArchive — 全局配置（占位符集中地）
 * ⚠️ 按 docs/AWS_SETUP_GUIDE.md 完成 AWS 配置后，把真实值填回这里。
 * 所有占位符以 YOUR_ 开头。
 */
window.APP_CONFIG = {
  /* ---- AWS 基础 ---- */
  region: 'us-east-1',               // 你的 AWS 区域（与创建资源时一致）

  /* ---- Cognito（Step 1）---- */
  cognitoClientId: '37n7349bmavmjkbnqgb1acjghp',   // App client 的 Client ID
  // 若 App client 勾选了 "Generate a client secret"，必须把 secret 填在这里（代码会自动计算 SECRET_HASH）；
  // 推荐改为无 secret 的 Public client 并留空（见 AWS_SETUP_GUIDE.md FAQ）。
  cognitoClientSecret: '1asb4m9smhfvrs6qn1bhrv6gn2nenvtp72heoq1g0vf9j04ppp9s',
  cognitoUserPoolId: 'us-east-1_rThAMvbnC',          // 仅 B/C 配置 API Gateway Authorizer 时使用

  /* ---- API Gateway（Step 5）---- */
  apiBaseUrl: 'https://5asagf7xx0.execute-api.us-east-1.amazonaws.com/prod/',  // 末尾必须带 /
  endpoints: {
    uploadUrl: 'upload-url',
    // Member C's protected API must return completed files with temporary,
    // browser-readable thumbnail/full URLs. See js/gallery.js for the contract.
    gallery: 'files'
  },

  /* ---- S3（Step 2）---- */
  bucketName: 'fit5225-s3-bucket-513636860535-us-east-1-an',

  /* ---- 桶目录约定（三人契约，勿改）---- */
  paths: {
    uploads: 'uploads/',       // A：用户上传的原文件
    thumbnails: 'thumbnails/', // B：缩略图
    models: 'models/'          // B：模型版本
  }
};
