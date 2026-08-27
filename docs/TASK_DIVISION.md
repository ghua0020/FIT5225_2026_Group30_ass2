# FIT5225 2026 S2 Assignment 2 — 三人任务划分

> **Pacific BioArchive: 多云无服务器野生动物观测平台**
> 截止：2026-08-30 23:55（权重 40%）
> 本文件是小组任务分工的唯一依据，改动需三人同意并更新契约。

---

## 1. 作业要求摘要

| 评分模块 | 权重 | 核心内容 |
|---|---|---|
| §3 认证授权 | 10% | 必须用 AWS Cognito；注册/登录/登出、邮箱验证+临时密码、未登录拦截跳转、token 安全传递、IAM 细粒度权限 |
| §4.1 模型处理 | (50%内) | 预训练模型可热更新（换模型不改 Lambda 代码） |
| §4.2 文件处理 | (50%内) | 上传触发事件→serverless 函数；checksum 去重；OpenCV 缩略图；ML 自动打标签；视频 1 帧/秒抽帧；写入高可用数据库 |
| §4.3 查询 | (50%内) | 6 种 API：按标签+最低计数（AND）、按物种、按缩略图 URL 反查原图、按上传文件查同标签文件（临时文件不入库）、批量增删标签（operation 1/0）、删除文件 |
| §4.4 通知 | (50%内) | SNS 按标签订阅发邮件 |
| §5 UI | 20% | 功能完整即可；不做 UI 最高封顶 D（70%） |
| §6 Demo+报告 | 20% | Demo 10%（全员到场）、Team Report 7%（贡献表每人≤30%）、Individual 3%（每人 500 词） |

**关键细节**：
- 数据包 `docs/PacificBioArchive.zip` 已提供 YOLO 模型（`model.pt`/`mdv5a.pt`）、`labels.txt`、`batch.py` 批处理参考代码、`requirements.txt`
- `docs/test_images.zip` 是 30 张带物种名的测试图（demo 直接用）
- 报告必须提及 GenAI 使用声明，否则 §6.2/6.3 直接 0 分
- 本作业只使用 **AWS 单云**（无需第二云）

---

## 2. 划分原则

按**功能域 + 数据流**划分：每人 = 自己域的「页面 + RESTful API + 云服务」。
- 三人都做云计算、都有页面、都独立可演示
- UI 用极简 HTML+JS（共享一个 `style.css`），不做视觉设计
- 工作量均衡（贡献比例约 33/33/34，每人不超过 30% 上限）

---

## 3. 云资源分配（AWS 单云）

```
AWS: Cognito(A) · S3(A) · Lambda(B) · API Gateway(A/C) · DynamoDB(C) · SNS(B发/C收)
```

---

## 4. 三人任务划分

### 成员 A — 账户与上传域（Auth & Upload）

- **页面**：注册/登录页、上传页
- **云**：AWS Cognito（用户池/客户端/邮件验证）、S3（建桶+目录结构）、API Gateway（上传端点）、IAM 策略
- **任务**：
  1. Cognito 注册（email/姓/名/密码）、邮箱验证、临时密码修改、登录/登出、token 存储与刷新
  2. 路由守卫：未登录一律跳注册页（所有页面生效）
  3. 文件上传（图片+视频，可直接 SDK 上传或 REST 端点）
  4. 去重：客户端计算 checksum，上传前查库拦截重复文件
  5. 输出共享认证工具（`auth.js` + token 校验 Lambda 帮助函数），B/C 的 API 直接复用
- **对应章节**：§3 全部分（10%）+ §4.2 上传/去重 + §5 上传页
- **依赖**：无（第一个动工，其余人等他发布 Cognito 配置）

### 成员 B — 智能处理链（Processing Pipeline）

- **页面**：文件库页（缩略图网格+标签展示、点击看原图、处理状态）
- **云**：AWS Lambda ×3（缩略图 / 视频抽帧 / 打标签）、S3 读写、模型版本存储、SNS 事件发布
- **任务**：
  1. §4.1 模型处理：`model.pt` 放 S3 按版本目录管理，Lambda 冷启动时按配置拉取——换模型只改配置不改代码
  2. §4.2 缩略图：OpenCV 等比缩放+压缩，写回 `thumbnails/`
  3. §4.2 视频抽帧：ffmpeg 抽 1 帧/秒再走图片检测
  4. §4.2 打标签：YOLO 检测物种 → tags[{name,count}] → 按物种归档目录 → 写 DynamoDB 记录（file_type、full_url、thumb_url、tags、checksum）
  5. 发布 SNS「新标签入库」事件（供 C 的通知消费）
- **对应章节**：§4.1 + §4.2 处理部分 + §5 文件库页
- **依赖**：A 的 bucket 约定（事件触发配置）；DynamoDB schema 与 C 提前定死（B 写、C 读）

### 成员 C — 查询与通知域（Query & Notification）

- **页面**：查询页（6 种查询表单+缩略图结果预览）、标签管理页（批量增删标签/删除文件）、通知设置页
- **云**：API Gateway（查询端点群）+ Lambda（查询函数）+ DynamoDB（schema 设计 + GSI 索引）+ SNS（主题/订阅/邮件）
- **任务**：
  1. 定义并建好 DynamoDB schema + GSI（支撑 AND+计数查询）
  2. §4.3 六种查询 API 全部实现（含"按文件查询"时临时调用 B 的检测函数、不落库；删除文件同时删存储对象+缩略图+DynamoDB 记录；批量标签操作 operation 1/0）
  3. §4.4 SNS 主题：按标签订阅/退订，消费 B 发布的新标签事件 → 发邮件通知
- **对应章节**：§4.3 + §4.4 + §5 查询/管理/设置页
- **依赖**：与 B 定死 schema（B 写 C 读）；B 提供检测函数调用约定

---

## 5. 接口契约（开工前 30 分钟定死，之后不许改）

| 契约 | 归属 | 内容 |
|---|---|---|
| 1. Bucket 命名/目录 | A 定义 | `uploads/`、`thumbnails/`、`models/v1/` 路径规则 |
| 2. DynamoDB schema + GSI | B/C 共同定死 | 以 [`DB_SCHEMA_V2.md`](DB_SCHEMA_V2.md) 为当前契约：`files` + `file_tags` + `subscriptions`、3 个 GSI、稳定 URL 和 SNS 消息格式 |
| 3. API 格式 | A/C 各自定义自己的端点 | RESTful JSON，统一 `Authorization: Bearer <cognito_token>` |
| 4. SNS 消息格式 | B 定义、C 消费 | `{file_id, tags[], full_url}` |
| 5. 共享认证工具 | A 输出 | `auth.js`（前端）+ token 校验 Lambda 层（后端），B/C 直接引用 |

---

## 6. 开发顺序

- **Day 0（半天）**：三人开会定契约；A 开始配 Cognito，B 本地跑通 `batch.py`+模型（先验证模型输出格式），C 建 DynamoDB schema
- **Day 1-2 并行**：A 完成认证+上传+去重；B 完成 3 个 Lambda+触发；C 完成查询 API+SNS（先用 mock 数据）
- **Day 3 集成**：端到端联调（此时才互相依赖），补通知、删文件等收尾
- **Day 4 演示+报告**：demo 每人讲自己域 1 分钟；Team Report 贡献表 33/33/34；Individual Report 各自写；别忘了 GenAI 声明

---

## 7. Git 约定（评分点）

作业要求所有成员必须自己 commit 代码作为贡献证据：

- 分支：`feature/auth-upload`（A）、`feature/processing`（B）、`feature/query-notify`（C），完成后合入 main
- 共享目录只有 `docs/` 契约文件和 `ui/style.css`，冲突面极小
- 仓库保持 private，最后分享给 teaching team
- 本文件（`docs/TASK_DIVISION.md`）由三人共同维护

---

## 8. 报告与演示分工（非开发任务）

| 项目 | 归属 | 说明 |
|---|---|---|
| Demo 架构讲解（3 分钟） | 三人各 1 分钟 | 每人讲自己的功能域 |
| Demo 功能演示（15 分钟） | 三人各自演示自己域 | 全员必须到场 |
| Team Report（7%，≤1000 词） | 共同完成 | 架构图（官方图标）、贡献表（每人≤30%）、用户指南、代码链接、GenAI 声明 |
| Individual Report（3%，每人 500 词） | 各自独立写 | 独立完成，避免抄袭 |
