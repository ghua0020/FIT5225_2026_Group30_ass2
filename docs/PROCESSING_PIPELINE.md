# Processing Pipeline - Basic Version

This document describes the implemented assignment baseline for Rubric 2.1.2 and 2.1.3.

## 1. Implemented flow

```text
Authenticated browser
  -> request presigned PUT URL
  -> PUT original media + signed checksum/user metadata
  -> S3 uploads/ ObjectCreated event
  -> Processing Lambda container
       -> download versioned models from S3 and cache in /tmp
       -> image: create compressed aspect-ratio-preserving thumbnail
       -> video: extract one frame at every whole second
       -> MegaDetector animal boxes
       -> SpeciesNet classification for each animal crop
       -> aggregate scientific-name counts
       -> atomic files + file_tags DynamoDB transaction
       -> publish tag-filtered SNS event
```

The database and SNS payloads follow [`DB_SCHEMA_V2.md`](DB_SCHEMA_V2.md).

## 2. Source layout

```text
backend/processing_pipeline/
├── config.py             # environment configuration
├── labels.py             # labels.txt parser
├── models.py             # model download/cache/load/inference
├── media.py              # thumbnails and one-frame-per-second extraction
├── storage.py            # S3, DynamoDB transaction, SNS adapters
├── pipeline.py           # processing orchestration
├── lambda_function.py    # S3 event entry point
├── local_run.py          # real-model local smoke-test CLI
├── Dockerfile            # Lambda container image
└── requirements.txt

backend/tests/processing_pipeline/
└── test_*.py             # unit tests kept outside the runtime image
```

## 3. Local verification

Run unit tests from the repository root:

```powershell
conda run -n FIT5225-A2 python -m pytest backend/tests/processing_pipeline -q
```

Run real inference with the supplied models:

```powershell
conda run -n FIT5225-A2 python -m backend.processing_pipeline.local_run `
  "D:\Desktop\FIT5225\A2\test_images\test_images\Felis_catus_3.JPG" `
  --md-model "D:\Desktop\FIT5225\A2\PacificBioArchive\mdv5a.pt" `
  --species-model "D:\Desktop\FIT5225\A2\PacificBioArchive\model.pt" `
  --labels "D:\Desktop\FIT5225\A2\PacificBioArchive\labels.txt" `
  --thumbnail "processing-output\Felis_catus_3-thumb.jpg" `
  --output "processing-output\Felis_catus_3-result.json"
```

Verified result on 2026-08-27:

```json
{
  "detection_count": 1,
  "tags": [
    {
      "name": "Felis_catus",
      "common_name": "domestic cat",
      "count": 1,
      "confidence": 0.996559
    }
  ]
}
```

The generated thumbnail is `480 x 320`, preserving the source aspect ratio.

## 4. Required AWS resources

Before enabling the S3 trigger, create:

1. `files` DynamoDB table and its three GSIs.
2. `file_tags` DynamoDB table.
3. `pba-tag-events` SNS topic if notifications are being demonstrated.
4. An ECR repository for the Processing Lambda container.
5. The Processing Lambda using the container image.

The exact DynamoDB keys and types are defined in [`DB_SCHEMA_V2.md`](DB_SCHEMA_V2.md).

## 5. Upload versioned models

Upload, but do not commit, the supplied files:

```powershell
aws s3 cp "D:\Desktop\FIT5225\A2\PacificBioArchive\mdv5a.pt" "s3://<bucket>/models/v1/mdv5a.pt"
aws s3 cp "D:\Desktop\FIT5225\A2\PacificBioArchive\model.pt" "s3://<bucket>/models/v1/model.pt"
aws s3 cp "D:\Desktop\FIT5225\A2\PacificBioArchive\labels.txt" "s3://<bucket>/models/v1/labels.txt"
```

To upgrade later, upload the three files under `models/v2/` and change only `MODEL_VERSION=v2`.

## 6. Build the Lambda container

Build from the repository root so the Dockerfile can copy the `backend` package:

```powershell
docker build -f backend/processing_pipeline/Dockerfile -t pba-processing:basic .
```

Push this image to ECR and select it when creating/updating the Lambda. The large PyTorch/MegaDetector dependencies are why the basic deployment uses a container image rather than a normal Lambda ZIP.

Suggested starting configuration for the assignment test set:

- architecture matching the built image;
- at least 4096 MB memory;
- at least 2 GB ephemeral storage;
- a long enough timeout for CPU inference and short demo videos;
- reserved concurrency kept low while testing to control AWS Academy cost.

Tune these values from CloudWatch timings rather than treating them as production defaults.

## 7. Lambda environment variables

Required:

```text
FILES_TABLE=files
FILE_TAGS_TABLE=file_tags
MODEL_VERSION=v1
```

Optional/defaulted:

```text
MODEL_BUCKET=<event bucket when omitted>
MODEL_PREFIX=models
UPLOAD_PREFIX=uploads/
THUMBNAIL_PREFIX=thumbnails/
DETECTOR_CONFIDENCE=0.05
CLASSIFIER_CONFIDENCE=0.0
THUMBNAIL_MAX_SIZE=480
THUMBNAIL_QUALITY=80
NOTIFY_TOPIC_ARN=<optional SNS topic ARN>
```

Do not set `LOCAL_MD_MODEL_PATH`, `LOCAL_SPECIES_MODEL_PATH`, or `LOCAL_LABELS_PATH` in AWS; those overrides are only for local diagnostics.

## 8. S3 event and CORS

Configure an ObjectCreated trigger with:

```text
Prefix: uploads/
```

Do not configure the entire bucket, because thumbnail writes must not recursively invoke the pipeline.

The browser PUT now includes:

```text
x-amz-meta-checksum
x-amz-meta-uploaded-by
```

The bucket CORS policy must allow the frontend origin, `PUT`, `Content-Type`, and these metadata headers. A basic development policy can allow all request headers, but the final policy should restrict the origin to the deployed frontend.

## 9. Minimum Processing Lambda IAM scope

Grant only:

- `s3:GetObject` on `uploads/*` and `models/*`;
- `s3:PutObject` on `thumbnails/*`;
- `dynamodb:GetItem` and `dynamodb:TransactWriteItems` on `files` and `file_tags`;
- `sns:Publish` on the configured topic when enabled;
- CloudWatch Logs permissions.

The upload-url Lambda also needs permission to sign `PutObject` requests containing object metadata.

## 10. Basic-version behaviour

- Images produce one JPEG thumbnail and automatic tag counts.
- Videos do not produce thumbnails; they sample one frame at each whole second.
- Video tag counts are the sum of classified animals across sampled frames.
- A media item with no detected animals stores `tags=[]` and `tag_counts={}` and publishes no SNS event.
- Failed processing writes no incomplete final database item; the Lambda error and traceback are recorded in CloudWatch and the S3 event can retry.
- Re-delivery uses the same UUIDv5 and overwrites the same final rows.

Advanced limitations and future improvements are intentionally tracked in [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md).
