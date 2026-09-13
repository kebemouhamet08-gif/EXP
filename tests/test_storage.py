import io
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from flask import Flask

import storage


def r2_config():
    return {
        'R2_ENDPOINT_URL': 'https://example.invalid',
        'R2_ACCESS_KEY_ID': 'access',
        'R2_SECRET_ACCESS_KEY': 'secret',
        'R2_BUCKET': 'private-bucket',
        'R2_REGION': 'auto',
    }


def test_local_storage_upload_download_delete_and_missing(tmp_path):
    backend = storage.LocalStorageBackend(tmp_path)
    backend.put('copies/a.pdf', io.BytesIO(b'data'), content_type='application/pdf')
    assert backend.exists('copies/a.pdf')
    app = Flask(__name__)
    with app.test_request_context():
        response = backend.response('copies/a.pdf', download_name='copie.pdf')
        response.direct_passthrough = False
        assert response.get_data() == b'data'
        response.close()
    backend.delete('copies/a.pdf')
    assert not backend.exists('copies/a.pdf')
    with app.test_request_context(), pytest.raises(FileNotFoundError):
        backend.response('copies/a.pdf')


def test_local_storage_denies_path_traversal(tmp_path):
    backend = storage.LocalStorageBackend(tmp_path)
    with pytest.raises(storage.StorageError):
        backend.put('../secret', io.BytesIO(b'bad'))


def test_s3_storage_uses_private_object_and_short_presigned_url(monkeypatch):
    client = MagicMock()
    client.generate_presigned_url.return_value = 'https://signed.invalid/object'
    monkeypatch.setattr(storage.boto3, 'client', lambda *_args, **_kwargs: client)
    backend = storage.S3CompatibleStorageBackend(r2_config())
    backend.put('subjects/a.pdf', io.BytesIO(b'data'), content_type='application/pdf')
    client.upload_fileobj.assert_called_once()
    app = Flask(__name__)
    with app.test_request_context():
        response = backend.response('subjects/a.pdf', download_name='sujet.pdf')
    assert response.status_code == 302
    assert response.location == 'https://signed.invalid/object'
    assert client.generate_presigned_url.call_args.kwargs['ExpiresIn'] == 300
    backend.delete('subjects/a.pdf')
    client.delete_object.assert_called_once_with(Bucket='private-bucket', Key='subjects/a.pdf')


def test_s3_missing_and_permission_denied(monkeypatch):
    client = MagicMock()
    missing = ClientError(
        {'Error': {'Code': '404'}, 'ResponseMetadata': {'HTTPStatusCode': 404}}, 'HeadObject'
    )
    client.head_object.side_effect = missing
    monkeypatch.setattr(storage.boto3, 'client', lambda *_args, **_kwargs: client)
    backend = storage.S3CompatibleStorageBackend(r2_config())
    assert backend.exists('missing') is False
    denied = ClientError(
        {'Error': {'Code': 'AccessDenied'}, 'ResponseMetadata': {'HTTPStatusCode': 403}}, 'HeadObject'
    )
    client.head_object.side_effect = denied
    with pytest.raises(storage.StorageError):
        backend.exists('denied')
