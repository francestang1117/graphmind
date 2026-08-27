"""S3 storage tests use a tiny fake client instead of a real MinIO server."""

from pathlib import Path

from app.services.object_storage import S3ObjectStorage


class FakeS3Client:
    def __init__(self):
        self.objects = {}
        self.deleted = []

    def put_object(self, Bucket, Key, Body, ContentType, Metadata):
        self.objects[(Bucket, Key)] = {
            "body": Body,
            "content_type": ContentType,
            "metadata": Metadata,
        }

    def delete_object(self, Bucket, Key):
        self.deleted.append((Bucket, Key))
        self.objects.pop((Bucket, Key), None)

    def download_file(self, Bucket, Key, Filename):
        Path(Filename).write_bytes(self.objects[(Bucket, Key)]["body"])

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return f"https://example.test/{Params['Bucket']}/{Params['Key']}?exp={ExpiresIn}"


def test_s3_storage_uploads_file_and_keeps_local_cache(tmp_path):
    client = FakeS3Client()
    storage = S3ObjectStorage(tmp_path, bucket="graphmind", client=client)

    info = storage.save_file(b"# Notes", "notes.md", "text/markdown", user_id="u1")

    assert info["storage_backend"] == "s3"
    assert info["object_key"].endswith(f"u1/{info['stored_filename']}")
    assert client.objects[("graphmind", info["object_key"])]["body"] == b"# Notes"
    assert Path(info["file_path"]).read_bytes() == b"# Notes"


def test_s3_storage_restores_missing_local_cache(tmp_path):
    client = FakeS3Client()
    storage = S3ObjectStorage(tmp_path, bucket="graphmind", client=client)
    info = storage.save_file(b"cached remotely", "remote.txt", "text/plain", user_id="u1")

    Path(info["file_path"]).unlink()
    restored = storage.ensure_local_file(info)

    assert restored.read_bytes() == b"cached remotely"


def test_s3_storage_deletes_local_and_remote_copy(tmp_path):
    client = FakeS3Client()
    storage = S3ObjectStorage(tmp_path, bucket="graphmind", client=client)
    info = storage.save_file(b"bye", "bye.txt", "text/plain", user_id="u1")

    assert storage.delete_file(info["stored_filename"], user_id="u1") is True

    assert ("graphmind", info["object_key"]) in client.deleted
    assert storage.get_file_info(info["stored_filename"], user_id="u1") is None


def test_s3_storage_can_sign_download_url(tmp_path):
    client = FakeS3Client()
    storage = S3ObjectStorage(tmp_path, bucket="graphmind", client=client)
    info = storage.save_file(b"download", "download.txt", "text/plain", user_id="u1")

    url = storage.presigned_download_url(info, expires_in=60)

    assert info["object_key"] in url
    assert "exp=60" in url


def test_s3_storage_keeps_same_content_separate_for_each_user(tmp_path):
    client = FakeS3Client()
    storage = S3ObjectStorage(tmp_path, bucket="graphmind", client=client)

    first = storage.save_file(b"shared bytes", "notes.md", "text/markdown", user_id="u1")
    second = storage.save_file(b"shared bytes", "notes.md", "text/markdown", user_id="u2")

    assert first["stored_filename"] == second["stored_filename"]
    assert first["file_path"] != second["file_path"]
    assert first["object_key"] != second["object_key"]
    assert storage.get_file_info(first["stored_filename"], user_id="u1")["user_id"] == "u1"
    assert storage.get_file_info(second["stored_filename"], user_id="u2")["user_id"] == "u2"

    assert storage.delete_file(first["stored_filename"], user_id="u1") is True
    assert storage.get_file_info(second["stored_filename"], user_id="u2") is not None
    assert ("graphmind", second["object_key"]) in client.objects
