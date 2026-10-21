from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from app.services.connectors.generic import service
from app.services.connectors.sharepoint_otp.ingester import SharedFolderIngester


@pytest.mark.parametrize(
    "code,status",
    [
        (None, "connected"),
        ("InvalidAccessKeyId", "auth_failed"),
        ("SignatureDoesNotMatch", "auth_failed"),
        ("403", "access_denied"),
        ("AccessDenied", "access_denied"),
        ("404", "unreachable"),
    ],
)
def test_s3_resource_check_only_reads_metadata_and_never_leaks_credentials(
    monkeypatch, code, status
):
    import boto3

    client = Mock()
    if code:
        client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": code, "Message": "secret-password"}}, "HeadBucket"
        )
    factory = Mock(return_value=client)
    monkeypatch.setattr(boto3, "client", factory)
    result = service.test_connection(
        "s3",
        {
            "values": {"bucket": "allowed-bucket", "access_key_id": "test-key"},
            "secrets": {"secret_access_key": "secret-password"},
        },
    )
    assert result["status"] == status
    assert "secret-password" not in str(result)
    client.head_bucket.assert_called_once_with(Bucket="allowed-bucket")
    client.close.assert_called_once()
    client.put_object.assert_not_called()
    client.list_objects_v2.assert_not_called()
    assert factory.call_args.kwargs["config"].retries == {"max_attempts": 0}


def test_s3_unconfigured_does_not_contact_external_service(monkeypatch):
    import boto3

    factory = Mock()
    monkeypatch.setattr(boto3, "client", factory)
    assert service._test_s3({"bucket": "bucket"}, {}) == ("not_configured", None)
    factory.assert_not_called()


def test_sharepoint_probe_does_not_download_create_local_directory_or_prune(tmp_path):
    client = Mock()
    consumed = []

    def walk(folder):
        consumed.append(folder)
        yield SimpleNamespace(name="first.pdf")
        raise AssertionError("Probe must not scan the whole folder")

    client.walk.side_effect = walk

    @contextmanager
    def factory():
        yield client

    output = tmp_path / "not-created"
    ingester = SharedFolderIngester(
        "/Shared/Documents", client_factory=factory, output_dir=output, prune_local_files=True
    )
    ingester.probe()
    assert consumed == ["/Shared/Documents"]
    assert not output.exists()
    client.download_file.assert_not_called()
