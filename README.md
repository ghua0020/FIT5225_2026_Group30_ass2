# Pacific BioArchive

A serverless cloud platform for automated wildlife media tagging — part of **FIT5225 2026 S2 Assignment 2** (Group 30).

Users upload wildlife images/videos; the system automatically detects species with an ML model (YOLO), generates thumbnails, tags files, and makes them searchable via REST APIs.

> **Cloud stack**: AWS single-cloud (Cognito, S3, Lambda, API Gateway, DynamoDB, SNS)
> **Due**: 2026-08-30 23:55

---

## Current Status

| Module | Owner | Status |
|---|---|---|
| **Auth** (sign up / sign in / sign out, email verification, route guard) | A | ✅ Done |
| **Upload** (SHA-256 checksum, dedup, presigned URL direct-to-S3) | A | ✅ Done |
| **Processing pipeline** (thumbnails, 1 frame/sec video extraction, ML tagging, DB transaction) | B | ✅ Basic version implemented and locally verified; AWS deployment pending |
| **Gallery** (thumbnail grid, tags, processing results) | B | ✅ Frontend and `GET /files` Lambda implemented; AWS route deployment required |
| **Query APIs** (tag/species/URL/file queries, tag management, delete) | C | ✅ Code done (deployment: `docs/C_QUERY_SETUP_GUIDE.md`) |
| **Notifications** (SNS tag subscriptions) | C | ✅ Code done (deployment: `docs/C_QUERY_SETUP_GUIDE.md`) |

### Current milestone

The next implementation target is the **Processing Pipeline**: S3-triggered image/video processing, thumbnail generation, one-frame-per-second video sampling, versioned ML inference, DynamoDB metadata updates, and tag-event publication.

Known security, reliability, integration, UI, and documentation issues have been recorded in [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md). They are intentionally deferred unless they block the Processing Pipeline or must be resolved before deployment/demo.

The current DynamoDB/S3/SNS contract shared by the Processing and Query modules is [`docs/DB_SCHEMA_V2.md`](docs/DB_SCHEMA_V2.md). It supersedes the earlier v1 draft for new implementation work.

Processing implementation, local verification, AWS resources, environment variables, IAM, and deployment steps are documented in [`docs/PROCESSING_PIPELINE.md`](docs/PROCESSING_PIPELINE.md).

## Implemented Features (Member A — Auth & Upload)

### Authentication (AWS Cognito)
- Sign up with email, first name, last name, password
- Email verification via confirmation code (Cognito auto-sent email)
- Resend verification code
- Sign in / sign out, token stored in `localStorage`
- **Route guard**: unauthenticated users are redirected to the sign-up page
- Automatic token refresh (refresh token)
- Backend protection: API Gateway **Cognito Authorizer** (reusable by Members B & C)

### Upload (S3 presigned URL)
- SHA-256 checksum computed client-side
- **Deduplication**: the complete SHA-256 is queried through DynamoDB's `checksum-index` and used as the deterministic S3 object key; conditional `If-None-Match: *` uploads prevent concurrent overwrites
- Presigned URL direct upload → no 10 MB API Gateway limit, large videos supported
- Upload triggers S3 events automatically → Member B's processing pipeline (when deployed)

### Shared utilities for the team
- `frontend/js/auth.js` — `Auth.apiGet()` / `Auth.authHeaders()` / `Auth.requireAuth()` for Members B & C

---

## Implemented Features (Member C — Query & Notification)

- §4.3 six query APIs: tags with minimum counts (AND) · by species · thumbnail → full image · search-by-file (temporary detection, not stored) · bulk add/remove tags (`operation` 1/0) · delete files (storage + database)
- §4.4 SNS notifications: subscribe / unsubscribe per species; email delivered by SNS FilterPolicy on message attribute `tags` (no SES); confirmed email subscriptions are reconciled from DynamoDB whenever the notification page loads
- Pages: `query.html`, `tags.html`, `notify.html`; shared `js/api.js` client (Bearer token via A's `auth.js`)

---

## Architecture

```
Browser (frontend/)
 ├─ signup / login ──HTTP──▶ Cognito public endpoint (no backend)
 └─ upload ──Bearer token──▶ API Gateway /upload-url (Cognito Authorizer)
                              └──▶ Lambda get-upload-url (dedup + presigned URL)
                                     └──▶ S3 uploads/  ◀──PUT direct── Browser
 S3 event ──▶ (Member B) Lambda: thumbnail / frame extraction / ML tagging ──▶ DynamoDB
 SNS notification (Member C)
```

## Repository Structure

```
frontend/
├── index.html        # authentication-aware entry route to Gallery or Sign-up
├── signup.html       # sign up + email verification
├── login.html        # sign in
├── upload.html       # upload page
├── gallery.html      # B: processing status and media gallery
├── query.html        # C: search (tags+count / species / thumbnail / by-file)
├── tags.html         # C: bulk add-remove tags, delete files
├── notify.html       # C: SNS tag subscriptions
├── css/style.css     # shared minimal stylesheet
└── js/
    ├── config.js     # ⚠️ 本地真实配置（.gitignore 已忽略，不入库）
    ├── config.example.js   # C: 可提交的占位符配置
    ├── auth.js       # shared auth utility (Cognito direct + session + apiGet)
    ├── api.js        # C: GET/POST 客户端（复用 auth.js，queryApiBaseUrl）
    ├── upload.js     # checksum → presigned → PUT to S3
    ├── gallery.js    # B: pending uploads → processed thumbnail/tag grid
    ├── query.js      # C: 查询页逻辑
    ├── tags.js       # C: 标签管理页逻辑
    └── notify.js     # C: 通知页逻辑
backend/lambdas/
├── get_upload_url/        # A: presigned URL + dedup Lambda
├── query-by-tags/         # C: query 1 tags+min-counts (AND)
├── query-by-species/      # C: query 2 by species
├── query-thumbnail/       # C: query 3 thumbnail -> full image
├── query-by-file/         # C: query 4 search by file (not stored)
├── tags-bulk/             # C: query 5 bulk add/remove tags
├── files-delete/          # C: query 6 delete files
├── files-list/            # B: paginated Gallery list with temporary S3 URLs
├── notify-subscribe/      # C: SNS subscribe
├── notify-unsubscribe/    # C: SNS unsubscribe
└── notify-list/           # C: list my subscriptions
backend/processing_pipeline/   # B: thumbnails / 1fps frames / ML tagging / DB transaction
docs/
├── TASK_DIVISION.md    # team task breakdown (3 members)
├── KNOWN_ISSUES.md     # deferred issues, priorities, fixes, and pipeline milestone
├── DB_SCHEMA_V2.md     # current files/file_tags/subscriptions and SNS contract
├── PROCESSING_PIPELINE.md # basic implementation, verification, and AWS setup
└── AWS_SETUP_GUIDE.md  # step-by-step AWS console setup guide
```

## Getting Started

### 1. Prerequisites
- AWS resources created per [docs/AWS_SETUP_GUIDE.md](docs/AWS_SETUP_GUIDE.md) (Cognito, S3, IAM, Lambda, API Gateway)

### 2. Configure
Fill real values into `frontend/js/config.js`:
- `region`, `cognitoClientId`, `cognitoUserPoolId`, `cognitoDomain`, `apiBaseUrl`, `bucketName`
- The browser must use a Cognito Public App Client. Never place a client secret in frontend code.

### 3. Run locally
```
cd frontend
python -m http.server 8000
```
Open `http://localhost:8000` (must be localhost — `crypto.subtle` requires a secure context).

### 4. Test flow
1. Visit `upload.html` while signed out → redirected to `signup.html`
2. Sign up → enter the verification code from your email → redirected to sign in
3. Sign in → upload an image from `docs/test_images.zip`
4. Upload the same file again → rejected as duplicate
5. Check the object in S3 `uploads/` bucket

## AWS Resources

| Resource | Name (example) | Owner |
|---|---|---|
| Cognito User Pool | `pba-user-pool` | A |
| S3 Bucket | `pba-media-<id>` (`uploads/ thumbnails/ models/`) | A |
| Lambda | `pba-get-upload-url` | A |
| API Gateway REST | `pba-api` (GET `/upload-url`, Cognito Authorizer) | A |
| Lambda pipeline ×3 | (thumbnail / extract / tag) | B |
| DynamoDB ×3 + GSIs | `files`, `file_tags`, `subscriptions` | C |
| Query/Notify Lambda ×9 | `query-by-*`, `tags-bulk`, `files-delete`, `notify-*` | C |
| API Gateway REST | `pba-query-api` (9 resources, Cognito Authorizer) | C |
| SNS topic | `pba-tag-events` (B publishes, C consumes) | C |

## Team

Task breakdown & contracts: [docs/TASK_DIVISION.md](docs/TASK_DIVISION.md) (Chinese)
AWS console setup: [docs/AWS_SETUP_GUIDE.md](docs/AWS_SETUP_GUIDE.md) (Chinese)
