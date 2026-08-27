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
| **Gallery** (thumbnail grid, tags, processing results) | B | 🚧 In development |
| **Query APIs** (tag/species/URL/file queries, tag management, delete) | C | 🚧 In development |
| **Notifications** (SNS tag subscriptions) | C | 🚧 In development |

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
- **Deduplication**: object keys carry a checksum prefix; `ListObjectsV2` prefix lookup rejects duplicate uploads instantly (database-layer dedup with DynamoDB auto-activates once Member B/C create the table)
- Presigned URL direct upload → no 10 MB API Gateway limit, large videos supported
- Upload triggers S3 events automatically → Member B's processing pipeline (when deployed)

### Shared utilities for the team
- `frontend/js/auth.js` — `Auth.apiGet()` / `Auth.authHeaders()` / `Auth.requireAuth()` for Members B & C

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
├── index.html        # entry page with nav (B/C links placeholder)
├── signup.html       # sign up + email verification
├── login.html        # sign in
├── upload.html       # upload page
├── css/style.css     # shared minimal stylesheet
└── js/
    ├── config.js     # ⚠️ ALL placeholders (YOUR_*) live here
    ├── auth.js       # shared auth utility (Cognito direct + session + apiGet)
    └── upload.js     # checksum → presigned → PUT to S3
backend/lambdas/get_upload_url/
└── lambda_function.py  # presigned URL + dedup Lambda
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
- `region`, `cognitoClientId`, `cognitoUserPoolId`, `apiBaseUrl`, `bucketName`
- `cognitoClientSecret`: leave empty for a Public (secret-less) app client; fill it if your app client has a secret

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
| DynamoDB table + GSI | (files table) | C |

## Team

Task breakdown & contracts: [docs/TASK_DIVISION.md](docs/TASK_DIVISION.md) (Chinese)
AWS console setup: [docs/AWS_SETUP_GUIDE.md](docs/AWS_SETUP_GUIDE.md) (Chinese)
