# Pacific BioArchive - Known Issues and Deferred Work

> Last reviewed: 2026-08-27  
> Status: Issues recorded for later resolution. The current implementation target is the **Processing Pipeline**.  
> Scope rule: Do not mix these deferred fixes into Processing Pipeline work unless an issue blocks pipeline integration or creates an immediate security risk.

## 1. Priority definitions

| Priority | Meaning |
|---|---|
| P0 | Security exposure or issue that must be resolved before public deployment/demo |
| P1 | Breaks a required assignment workflow or blocks integration |
| P2 | Reliability, usability, maintainability, or documentation issue |

## 2. Deferred issues

### KI-001 - Cognito app client secret is exposed in browser code and Git history

- **Priority:** P0
- **Affected area:** `frontend/js/config.js`, Cognito App Client
- **Current behaviour:** A real Cognito client secret is stored in a JavaScript file delivered to the browser and committed to Git.
- **Impact:** Browser applications cannot keep a client secret confidential. Anyone with access to the page or repository can read it.
- **Planned resolution:**
  1. Disable/delete the existing Cognito App Client or rotate the exposed credential.
  2. Create a Public App Client without a generated secret.
  3. Leave `cognitoClientSecret` empty and remove secret-hash logic from the browser flow.
  4. Ensure no secret is included in future commits or screenshots.
- **Acceptance criteria:** Registration, confirmation, login and refresh work with a secret-less Public App Client; the old client can no longer be used.
- **Status:** Deferred, but must be fixed before public deployment or demo.

### KI-002 - Refresh-token implementation is unreliable

- **Priority:** P1
- **Affected area:** `frontend/js/auth.js`
- **Current behaviour:** Refresh authentication calculates `SECRET_HASH` with an incorrect/unclear username value, and `saveSession()` may overwrite the existing refresh token because Cognito normally does not issue a new refresh token in a refresh response.
- **Impact:** A session may fail to refresh, or may refresh once and then lose the ability to refresh again.
- **Planned resolution:** Move to a secret-less Public App Client, preserve the old refresh token when the response omits one, and add expiry/refresh tests.
- **Acceptance criteria:** An expired ID token refreshes successfully at least twice without requiring a new login.
- **Status:** Deferred.

### KI-003 - Logout only clears local storage

- **Priority:** P2
- **Affected area:** `frontend/js/auth.js`
- **Current behaviour:** Logout removes local tokens but does not revoke the refresh token or perform Cognito global sign-out.
- **Impact:** A copied refresh token may remain valid after the user clicks Sign out.
- **Planned resolution:** Use Cognito `RevokeToken` or `GlobalSignOut`, then clear local state.
- **Acceptance criteria:** A token refresh attempted after logout is rejected.
- **Status:** Deferred.

### KI-004 - Upload deduplication is not atomic

- **Priority:** P1
- **Affected area:** `backend/lambdas/get_upload_url/lambda_function.py`, future DynamoDB schema
- **Current behaviour:** The Lambda checks DynamoDB/S3 first and issues a presigned URL afterwards. Concurrent requests can both pass the check. S3 matching uses only the first 16 checksum characters.
- **Impact:** Duplicate files can still be uploaded, particularly under concurrent requests or partial AWS failures.
- **Planned resolution:** Reserve the complete SHA-256 checksum using a DynamoDB conditional write before issuing a presigned URL. Use a dedicated checksum key/record and explicit upload states.
- **Acceptance criteria:** Two concurrent requests with the same checksum result in one upload reservation and one duplicate response.
- **Status:** Deferred; the Processing Pipeline schema must remain compatible with the future fix.

### KI-005 - DynamoDB fallback Scan can miss duplicates

- **Priority:** P1
- **Affected area:** `backend/lambdas/get_upload_url/lambda_function.py`
- **Current behaviour:** The fallback Scan combines a filter with `Limit=1`; the limit applies to evaluated items, not matching items, and pagination is not performed.
- **Impact:** A matching checksum elsewhere in the table may not be found.
- **Planned resolution:** Require a checksum key/GSI and remove the Scan fallback, or paginate correctly for diagnostic use only.
- **Acceptance criteria:** Duplicate detection never relies on a single-item filtered Scan.
- **Status:** Deferred.

### KI-006 - Upload record lacks integration metadata

- **Priority:** P1
- **Affected area:** upload URL Lambda, S3 object metadata, DynamoDB media record
- **Current behaviour:** The upload flow does not persist a full checksum, `fileId`, Cognito `sub`, uploader, original filename, timestamps, or processing status before the S3 PUT.
- **Impact:** The Processing Pipeline receives an S3 event but cannot reliably associate the object with a user and complete database record.
- **Planned resolution:** Before issuing the URL, create an `UPLOADING` media record and/or sign required S3 metadata. Use a stable `fileId` to join the upload event to DynamoDB.
- **Acceptance criteria:** An S3 event can deterministically locate one media record containing the full checksum and uploader identity.
- **Status:** Deferred as an auth/upload fix, but the Processing Pipeline must define and document the required contract now.

### KI-007 - Large-file checksum loads the whole file into browser memory

- **Priority:** P2
- **Affected area:** `frontend/js/upload.js`
- **Current behaviour:** `file.arrayBuffer()` loads the complete image/video before SHA-256 calculation.
- **Impact:** Large videos may freeze or crash the browser despite direct S3 upload supporting large objects.
- **Planned resolution:** Add a defensible upload-size limit and, if needed, implement chunked hashing/multipart upload.
- **Acceptance criteria:** Supported maximum-size videos upload without excessive browser memory consumption.
- **Status:** Deferred.

### KI-008 - API helper does not reject all non-success responses

- **Priority:** P1
- **Affected area:** `frontend/js/auth.js`
- **Current behaviour:** `Auth.apiGet()` handles HTTP 401 but otherwise returns parsed JSON for 403/404/500 responses.
- **Impact:** Callers may treat error payloads as successful data and fail later with misleading errors.
- **Planned resolution:** Check `resp.ok`, parse a consistent error envelope, refresh/retry once when appropriate, and throw typed errors.
- **Acceptance criteria:** Every non-2xx response reaches the UI as a clear error and is never consumed as success data.
- **Status:** Deferred.

### KI-009 - Authentication and page-state UI defects

- **Priority:** P2
- **Affected area:** `frontend/index.html`, `frontend/login.html`, `frontend/signup.html`
- **Current behaviour:**
  - The home page may show both guest and authenticated panels after login.
  - The unconfirmed-user message inserts an HTML link through `textContent`, so the link is displayed as text.
  - A pending verification email is not reliably restored into the confirmation UI after navigation/reload.
- **Impact:** Confusing registration and login experience.
- **Planned resolution:** Make guest/user states mutually exclusive, create links as DOM elements (or use safe fixed markup), and restore the pending confirmation step on load.
- **Acceptance criteria:** Registration, reload, verification, login and logout work without contradictory page states.
- **Status:** Deferred.

### KI-010 - Placeholder navigation links remain clickable

- **Priority:** P2
- **Affected area:** `frontend/index.html`, `frontend/upload.html`, `frontend/css/style.css`
- **Current behaviour:** Gallery/Search/Tags/Notifications links are visually disabled but still navigate to files that do not exist.
- **Impact:** Users reach 404 pages.
- **Planned resolution:** Add pages as their modules are implemented; until then remove the `href` or block pointer/keyboard activation accessibly.
- **Acceptance criteria:** Navigation contains no link to a missing page.
- **Status:** Deferred; expected to disappear as B/C pages are implemented.

### KI-011 - Upload validation and multi-file UI are incomplete

- **Priority:** P2
- **Affected area:** `frontend/upload.html`, `frontend/js/upload.js`, upload URL Lambda
- **Current behaviour:** The file picker is single-file although JavaScript loops over multiple files. MIME type, extension, checksum format and file size are not validated server-side.
- **Impact:** Unsupported or oversized objects can receive upload URLs; advertised multi-file behaviour is unavailable.
- **Planned resolution:** Define supported media types and size limits, validate them in the Lambda, and either add `multiple` or simplify the JavaScript to single-file behaviour.
- **Acceptance criteria:** Unsupported input is rejected before upload and the UI behaviour matches the implementation.
- **Status:** Deferred.

### KI-012 - Documentation contains missing/stale references

- **Priority:** P2
- **Affected area:** `README.md`, `docs/`
- **Current behaviour:** README refers to `docs/AWS_SETUP_GUIDE.md` and `docs/test_images.zip`, which are absent. The home page still describes the solution as multi-cloud although the current teaching-team clarification is AWS single-cloud.
- **Impact:** New team members cannot reproduce setup and report/demo wording may conflict with the corrected scope.
- **Planned resolution:** Add or correct the setup guide and resource instructions; replace stale multi-cloud wording where appropriate.
- **Acceptance criteria:** Every repository link resolves and all architecture descriptions consistently state AWS single-cloud.
- **Status:** Deferred.

### KI-013 - No automated tests or reproducible AWS deployment definition

- **Priority:** P2
- **Affected area:** whole repository
- **Current behaviour:** There are no unit/integration tests, dependency manifests for deployed functions, or SAM/CDK/Terraform/CloudFormation definitions.
- **Impact:** Current AWS resources and permissions cannot be reproduced or verified from the repository; regressions are difficult to detect.
- **Planned resolution:** Add focused unit tests, an end-to-end smoke-test checklist, pinned Lambda dependencies, and either IaC or an accurate manual deployment guide.
- **Acceptance criteria:** A clean environment can reproduce the system and run the core smoke tests from documented steps.
- **Status:** Deferred.

### KI-014 - Git contribution evidence currently represents one member only

- **Priority:** P1
- **Affected area:** Git workflow and assignment evidence
- **Current behaviour:** Current tracked commits are authored by one member; Processing, Query and Notification modules have no visible member commits yet.
- **Impact:** The repository does not yet demonstrate all members' individual contributions as required by the assignment.
- **Planned resolution:** Each member works through their own account/feature branch and makes meaningful commits and pull requests for their assigned domain.
- **Acceptance criteria:** Git history clearly shows code, tests and documentation contributed by every member.
- **Status:** Ongoing team-process item.

### KI-015 - Large model cold starts and repeated S3 downloads

- **Priority:** P2
- **Affected area:** Processing Lambda runtime
- **Current behaviour:** The basic version downloads the selected model version to `/tmp` and caches the loaded models only for the lifetime of a warm Lambda execution environment.
- **Impact:** New environments have high cold-start latency and consume model-download bandwidth.
- **Future resolution:** Evaluate EFS-mounted models, provisioned concurrency, smaller/quantised models, or a dedicated inference service after measuring the basic version.
- **Status:** Deferred; container + warm-cache behaviour is sufficient for the basic assignment version.

### KI-016 - Long videos may exceed one Lambda invocation

- **Priority:** P1
- **Affected area:** Video processing
- **Current behaviour:** The basic version decodes one process from the beginning to the end of the video and performs inference on one frame per second.
- **Impact:** Long/high-resolution videos can exceed available time, memory, or ephemeral storage.
- **Future resolution:** Add a duration limit or split videos into chunks using Step Functions/SQS and merge tag results.
- **Status:** Deferred; demo videos must remain short.

### KI-017 - Video counts can count the same animal in multiple seconds

- **Priority:** P2
- **Affected area:** Video tag aggregation
- **Current behaviour:** Counts are summed across sampled frames.
- **Impact:** An animal visible for several seconds is counted several times rather than tracked as one individual.
- **Future resolution:** Define the expected video-count semantics and add object tracking or use maximum simultaneous count per species.
- **Status:** Deferred; the basic version follows the required one-frame-per-second sampling rule.

### KI-018 - Model confidence and bounding boxes are not persisted

- **Priority:** P2
- **Affected area:** DynamoDB schema and diagnostics
- **Current behaviour:** Inference produces confidence/bounding boxes locally, but v2 intentionally stores only tag names and counts.
- **Impact:** The database cannot explain an individual prediction or support confidence filtering.
- **Future resolution:** Add a separate diagnostics table or a later schema version after B/C agreement.
- **Status:** Deferred by `DB_SCHEMA_V2.md`.

### KI-019 - Media codec coverage depends on the OpenCV container build

- **Priority:** P2
- **Affected area:** Video frame extraction
- **Current behaviour:** `opencv-python-headless` handles common codecs available in its wheel.
- **Impact:** Some MOV/MKV/HEVC files may fail even when their extension is accepted.
- **Future resolution:** Validate an explicit supported-codec list or package a controlled FFmpeg build.
- **Status:** Deferred; use short H.264 MP4/standard AVI demo files.

### KI-020 - No DLQ or operational replay workflow

- **Priority:** P2
- **Affected area:** S3/Lambda failure handling
- **Current behaviour:** Failures raise an exception for normal Lambda retry and are visible in CloudWatch, but there is no dead-letter queue or operator replay tool.
- **Impact:** Persistent failures require manual investigation and re-upload/replay.
- **Future resolution:** Add SQS between S3 and the processor, a DLQ, alarms, and a controlled replay command.
- **Status:** Deferred.

### KI-021 - Model files are not integrity-checked after download

- **Priority:** P2
- **Affected area:** Model version management
- **Current behaviour:** A non-empty cached file is reused without comparing a configured checksum/version manifest.
- **Impact:** A partial/corrupt or unexpectedly replaced model may remain cached until the execution environment is recycled.
- **Future resolution:** Store a version manifest with SHA-256 values and verify downloads before loading.
- **Status:** Deferred.

## 3. Current milestone - Processing Pipeline

The next implementation milestone is the AWS Processing Pipeline owned by Member B.

### In scope

1. Define the S3-event-to-DynamoDB integration contract.
2. Load the versioned ML model from `models/<version>/` without hard-coding a model into source code.
3. Process uploaded images and videos from `uploads/`.
4. Generate aspect-ratio-preserving compressed thumbnails for images.
5. Extract exactly one frame per second from videos.
6. Run species detection and aggregate `{name, count}` tags.
7. Write/update media metadata and processing status in DynamoDB.
8. Publish a stable tag event for the future notification module.
9. Provide a Gallery/API path for observing processing state and results.
10. Add tests and failure handling for unsupported/corrupt media and inference errors.

### Required status flow

```text
UPLOADING -> UPLOADED -> PROCESSING -> COMPLETED
                                  \-> FAILED
```

### Pipeline completion criteria

- Uploading a supported image triggers processing automatically.
- One thumbnail is produced without recursively retriggering the original-upload handler.
- Species tags, counts, original key, thumbnail key, model version and status are stored in DynamoDB.
- Uploading a supported video samples one frame per second and stores aggregated tags.
- Replacing the configured model version does not require editing Lambda source code.
- Failed jobs have a visible `FAILED` status and a useful error message/log entry.
- The same S3 event can be retried without producing duplicate thumbnails or duplicate media records.

## 4. Review rule

When a deferred issue is fixed, update its status and record:

- commit or pull request;
- test evidence;
- AWS resource/configuration change, if any;
- date verified.
