import json

from backend.processing_pipeline.storage import DynamoMediaRepository, SnsNotifier


class FakeDynamoClient:
    def __init__(self):
        self.transaction = None

    def get_item(self, **kwargs):
        return {}

    def transact_write_items(self, **kwargs):
        self.transaction = kwargs["TransactItems"]


class FakeSnsClient:
    def __init__(self):
        self.request = None

    def publish(self, **kwargs):
        self.request = kwargs


def test_repository_writes_files_and_file_tags_transaction() -> None:
    client = FakeDynamoClient()
    repository = DynamoMediaRepository(client, "files", "file_tags")
    repository.save_media(
        {
            "file_id": "a591b519-18c1-5e2a-887d-5895f589e207",
            "checksum": "a" * 64,
            "file_type": "image",
            "tags": ["Felis_catus"],
            "tag_counts": {"Felis_catus": 1},
            "full_url": "https://bucket.s3.us-east-1.amazonaws.com/uploads/cat.jpg",
            "thumb_url": "https://bucket.s3.us-east-1.amazonaws.com/thumbnails/cat.jpg",
            "uploaded_by": "user-sub",
            "created_at": 1787800123456,
        }
    )
    assert client.transaction is not None
    assert len(client.transaction) == 2
    assert client.transaction[0]["Put"]["TableName"] == "files"
    assert client.transaction[1]["Put"]["TableName"] == "file_tags"


def test_sns_message_matches_contract() -> None:
    client = FakeSnsClient()
    notifier = SnsNotifier(client, "arn:aws:sns:us-east-1:123:pba-tag-events")
    notifier.publish(
        {
            "file_id": "file-id",
            "tags": ["Felis_catus"],
            "full_url": "https://example/cat.jpg",
            "created_at": 1787800123456,
        }
    )
    body = json.loads(client.request["Message"])
    assert body["tags"] == ["Felis_catus"]
    assert client.request["MessageAttributes"]["tags"] == {
        "DataType": "String.Array",
        "StringValue": '["Felis_catus"]',
    }
