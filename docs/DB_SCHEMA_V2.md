# Pacific BioArchive - DynamoDB Data Contract v2

> Effective date: 2026-08-27  
> Region: `us-east-1`  
> Capacity mode: On-demand  
> Status: Current B-write / C-read-update-delete contract. Any incompatible change must be agreed by the team and recorded in a new version.

## 1. Decisions introduced in v2

This contract replaces the supplied v1 contract for new implementation work.

1. Uploads carry the complete SHA-256 checksum and Cognito `sub` in signed S3 object metadata.
2. `files.tags` is a DynamoDB `List<String>`, not a `StringSet`, so a valid no-animal result can store an empty list.
3. `full_url` and `thumb_url` are stable S3 HTTPS URLs without presigned query parameters.
4. The base `files` record contains only the agreed business fields. Processing status/error/model diagnostics remain CloudWatch concerns for the basic version.
5. Every `created_at` value, including SNS messages, is an epoch-millisecond Number.
6. Successful inference updates both `files` and `file_tags`; SNS is published only after both tables are updated successfully.

## 2. AWS resources

| Resource | Purpose | Primary key / index |
|---|---|---|
| `files` table | One final record per image/video | PK `file_id`; GSIs `thumb-index`, `full-index`, `checksum-index` |
| `file_tags` table | Reverse tag index for AND/count queries | PK `tag`, SK `file_id` |
| `subscriptions` table | User-to-tag notification preferences | PK `user_sub`, SK `tag` |
| Media S3 bucket | Original media, thumbnails, versioned models | Prefixes defined below |
| `pba-tag-events` SNS topic | Tag-filtered email notifications | `tags` message attribute |

## 3. S3 object contract

### 3.1 Key layout

```text
uploads/<checksum-first-16>-<original-file-name>
thumbnails/<checksum-first-16>-<original-file-stem>.jpg
models/<model-version>/mdv5a.pt
models/<model-version>/model.pt
models/<model-version>/labels.txt
```

Examples:

```text
uploads/a81c47e2f109e880-cat.png
thumbnails/a81c47e2f109e880-cat.jpg
models/v1/model.pt
```

Only `uploads/` is configured as the S3 ObjectCreated trigger prefix. Writing a thumbnail must not trigger the processing Lambda again.

### 3.2 Required original-object metadata

The upload-url Lambda must sign these metadata fields into the presigned PUT request:

| S3 metadata key | Value | Required |
|---|---|---|
| `checksum` | Complete lowercase 64-character SHA-256 | Yes |
| `uploaded-by` | Cognito user `sub` from API Gateway authorizer claims | Yes |

The browser must include the headers returned by the upload-url API in its S3 PUT:

```text
x-amz-meta-checksum: <complete SHA-256>
x-amz-meta-uploaded-by: <Cognito sub>
```

S3 metadata keys are read through `HeadObject.Metadata` as lowercase keys. The processing Lambda must fail the record and write no final database rows if either value is missing or malformed.

### 3.3 Stable URL format

Database URLs use the stable, unsigned form:

```text
https://<bucket>.s3.<region>.amazonaws.com/<percent-encoded-object-key>
```

Rules:

- Never store a presigned URL in DynamoDB.
- URL path segments must be percent-encoded consistently.
- Query APIs generate a temporary presigned URL only when returning an object to an authenticated client.
- When a client submits a presigned thumbnail/full URL, the query API removes its query string and normalises the remaining URL before querying a GSI.

## 4. Deterministic `file_id`

The processing Lambda generates a standard UUIDv5 from the canonical S3 URI:

```python
from uuid import NAMESPACE_URL, uuid5

file_id = str(uuid5(NAMESPACE_URL, f"s3://{bucket}/{key}"))
```

This provides:

- a valid UUID string;
- the same ID for repeated delivery of the same S3 event;
- idempotent overwrites instead of duplicate media rows.

## 5. `files` table

Table name: `files`  
Primary key: `file_id` (String)

| Attribute | DynamoDB type | Required | Definition |
|---|---|---:|---|
| `file_id` | String | Yes | Deterministic UUIDv5 defined above |
| `checksum` | String | Yes | Complete client-calculated SHA-256 from S3 metadata |
| `file_type` | String | Yes | Exactly `image` or `video` |
| `tags` | List<String> | Yes | Sorted unique scientific names; may be `[]` |
| `tag_counts` | Map<String, Number> | Yes | Per-species detected count; may be `{}` |
| `full_url` | String | Yes | Stable HTTPS URL for the original object |
| `thumb_url` | String | Image only | Stable HTTPS URL for the JPEG thumbnail; absent for video |
| `uploaded_by` | String | Yes | Cognito `sub` from S3 metadata |
| `created_at` | Number | Yes | S3 object creation time in epoch milliseconds |

Example image record:

```json
{
  "file_id": "a591b519-18c1-5e2a-887d-5895f589e207",
  "checksum": "a81c47e2f109e8802d7212e4081b12f092fa2b6f16d0e8b653ee0bfb21d76d7a",
  "file_type": "image",
  "tags": ["Felis_catus"],
  "tag_counts": {
    "Felis_catus": 1
  },
  "full_url": "https://pba-media.s3.us-east-1.amazonaws.com/uploads/a81c47e2f109e880-cat.jpg",
  "thumb_url": "https://pba-media.s3.us-east-1.amazonaws.com/thumbnails/a81c47e2f109e880-cat.jpg",
  "uploaded_by": "6a22d43e-6fd1-4df2-bb85-28473a3efc60",
  "created_at": 1787800123456
}
```

Valid no-animal result:

```json
{
  "tags": [],
  "tag_counts": {}
}
```

No `file_tags` rows and no SNS tag notification are created for a no-animal result.

### 5.1 GSIs

| GSI | Partition key | Purpose |
|---|---|---|
| `thumb-index` | `thumb_url` | Thumbnail URL to full image lookup; bulk tag/delete target lookup |
| `full-index` | `full_url` | Full image/video URL lookup; bulk tag/delete target lookup |
| `checksum-index` | `checksum` | Upload deduplication lookup |

Recommended projection for all three indexes: `ALL` for the assignment-sized data set and simpler API implementation.

Images participate in all three indexes. Videos omit `thumb_url`, so they do not appear in `thumb-index`.

## 6. `file_tags` table

Table name: `file_tags`  
Partition key: `tag` (String)  
Sort key: `file_id` (String)

| Attribute | DynamoDB type | Required | Definition |
|---|---|---:|---|
| `tag` | String | Yes | Scientific species name, e.g. `Felis_catus` |
| `file_id` | String | Yes | Matches `files.file_id` |
| `count` | Number | Yes | Detected count, at least 1 |
| `file_type` | String | Yes | `image` or `video` |
| `full_url` | String | Yes | Copied from `files` |
| `thumb_url` | String | Image only | Copied from `files`; absent for video |
| `created_at` | Number | Yes | Same epoch-millisecond value as `files.created_at` |

Example:

```json
{
  "tag": "Felis_catus",
  "file_id": "a591b519-18c1-5e2a-887d-5895f589e207",
  "count": 1,
  "file_type": "image",
  "full_url": "https://pba-media.s3.us-east-1.amazonaws.com/uploads/a81c47e2f109e880-cat.jpg",
  "thumb_url": "https://pba-media.s3.us-east-1.amazonaws.com/thumbnails/a81c47e2f109e880-cat.jpg",
  "created_at": 1787800123456
}
```

### 6.1 Tag naming rule

All automatic, manual, query, and notification operations use the scientific model label exactly as exposed by `labels.txt`, normalised to:

```text
Genus_species
```

Examples:

```text
Felis_catus
Canis_dingo
Uromys_caudimaculatus
```

Common names are presentation-only and are not database keys.

### 6.2 Processing write rule

After successful inference:

1. Build one final `files` item.
2. Build one `file_tags` item per non-zero tag.
3. Read the previous `files.tags` value when reprocessing an existing `file_id`.
4. Delete stale `file_tags` rows that are no longer present.
5. Write the `files` item and tag-row puts/deletes together with DynamoDB `TransactWriteItems`.
6. Publish SNS only after the transaction succeeds.

S3 retries therefore overwrite the same UUIDv5 record and tag rows.

### 6.3 Query algorithms

#### Multiple tags with minimum counts

For each requested tag:

1. `Query` `file_tags` with `PK = tag`.
2. Retain rows where `count >= requested minimum`.
3. Intersect the resulting `file_id` sets across all tags.

This is logical AND, never OR.

#### Single species

`Query` `file_tags` using `PK = species`.

#### Uploaded query file

Run the same inference pipeline without writing to S3/DynamoDB permanently, then intersect `file_id` sets for every detected tag.

## 7. Manual tag update rules

### Add (`operation = 1`)

- If the tag is absent, add it to `files.tags`, set `files.tag_counts[tag] = 1`, and create the matching `file_tags` row with `count = 1`.
- If the tag exists, preserve its current count.

### Remove (`operation = 0`)

- Remove the tag from `files.tags` and `files.tag_counts`.
- Delete the matching `file_tags` row.
- If the tag is absent, ignore it without failing the request.

The `files` update and `file_tags` put/delete must be in the same DynamoDB transaction.

## 8. Delete-file rules

For every requested URL:

1. Normalise the URL and locate the `files` item through `full-index` or `thumb-index`.
2. Delete the original S3 object.
3. Delete the thumbnail object for an image.
4. Delete every corresponding `file_tags` row.
5. Delete the `files` row.

Partial failures must be returned per URL. A later retry must be safe when an object or row is already absent.

## 9. `subscriptions` table

Table name: `subscriptions`  
Partition key: `user_sub` (String)  
Sort key: `tag` (String)

| Attribute | DynamoDB type | Required | Definition |
|---|---|---:|---|
| `user_sub` | String | Yes | Cognito user `sub` |
| `tag` | String | Yes | Scientific species name |
| `email` | String | Yes | Confirmed notification email |
| `created_at` | Number | Yes | Epoch milliseconds |

One user subscribing to N tags creates N rows.

## 10. SNS event contract

Topic name: `pba-tag-events`  
Lambda environment variable: `NOTIFY_TOPIC_ARN`

Message:

```json
{
  "file_id": "a591b519-18c1-5e2a-887d-5895f589e207",
  "tags": ["Felis_catus"],
  "full_url": "https://pba-media.s3.us-east-1.amazonaws.com/uploads/a81c47e2f109e880-cat.jpg",
  "created_at": 1787800123456
}
```

Message attributes:

```python
{
    "tags": {
        "DataType": "String.Array",
        "StringValue": '["Felis_catus"]'
    }
}
```

Publish rules:

- Processing Pipeline publishes only after a successful `files` + `file_tags` transaction.
- Manual tag addition publishes after its transaction succeeds.
- Empty tag lists do not publish an event.
- SNS `created_at` uses epoch milliseconds.

Subscription filter example:

```json
{
  "tags": ["Felis_catus", "Canis_dingo"]
}
```

## 11. Processing Lambda environment variables

| Variable | Required | Example |
|---|---:|---|
| `FILES_TABLE` | Yes | `files` |
| `FILE_TAGS_TABLE` | Yes | `file_tags` |
| `MODEL_BUCKET` | No | Defaults to media event bucket |
| `MODEL_PREFIX` | No | `models` |
| `MODEL_VERSION` | Yes | `v1` |
| `NOTIFY_TOPIC_ARN` | No | SNS topic ARN |
| `UPLOAD_PREFIX` | No | `uploads/` |
| `THUMBNAIL_PREFIX` | No | `thumbnails/` |

Changing from `models/v1/` to `models/v2/` requires only uploading the new model files and changing `MODEL_VERSION`; source code remains unchanged.

## 12. Minimum IAM permissions

Processing Lambda needs only:

- `s3:GetObject` for `uploads/*` and `models/*`;
- `s3:PutObject` for `thumbnails/*`;
- `dynamodb:GetItem` and `dynamodb:TransactWriteItems` for `files` and `file_tags`;
- `sns:Publish` for `pba-tag-events` when notifications are enabled;
- CloudWatch Logs permissions.

The upload-url Lambda separately needs:

- `s3:PutObject` for `uploads/*`;
- `s3:ListBucket` if retaining the basic S3-prefix duplicate check;
- `dynamodb:Query` on `checksum-index` when database deduplication is enabled.

## 13. Base-version exclusions

The following are intentionally not added to the frozen business tables in the base version:

- processing status/history;
- error details;
- inference confidence and bounding boxes;
- model performance metrics;
- frame-level video results;
- presigned URLs;
- thumbnails for videos.

These remain CloudWatch/runtime concerns or future-schema candidates. They must not be added silently because B and C share this contract.

