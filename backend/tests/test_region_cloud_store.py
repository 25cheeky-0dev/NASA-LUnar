from unittest.mock import Mock

import pytest

from app.regions import store


@pytest.fixture
def cloud_store(monkeypatch):
    pytest.importorskip('google.cloud.storage')
    monkeypatch.delenv('WISPR_DATABASE_URL', raising=False)
    monkeypatch.setenv('WISPR_REGION_BUCKET', 'test-private-bucket')
    monkeypatch.setenv('K_SERVICE', 'test-service')
    client = Mock()
    monkeypatch.setattr(store, 'cloud_client', lambda: client)
    return client.bucket.return_value.blob.return_value


def test_cloud_record_survives_new_client_and_update(cloud_store, monkeypatch):
    objects = {}
    def upload(value, **kwargs):
        objects['data'] = value.encode()
    cloud_store.upload_from_string.side_effect = upload
    store.put('job', 'job-1', {'status': 'RUNNING'})
    store.put('job', 'job-1', {'status': 'COMPLETE', 'result': {'elevation': 42}})
    # A fresh client reads the durable object, not any process-local cache.
    replacement = Mock()
    replacement.bucket.return_value.blob.return_value.download_as_bytes.return_value = objects['data']
    monkeypatch.setattr(store, 'cloud_client', lambda: replacement)
    assert store.get('job', 'job-1')['result']['elevation'] == 42


def test_object_identity_is_bounded_and_separates_kinds(cloud_store):
    client = store.cloud_client()
    store.cloud_blob('region', '../../unsafe')
    first = client.bucket.return_value.blob.call_args.args[0]
    store.cloud_blob('job', '../../unsafe')
    second = client.bucket.return_value.blob.call_args.args[0]
    assert first != second
    assert first.startswith('region-state/') and first.endswith('.json')
    assert '..' not in first and len(first.split('/')[1]) == 69


def test_missing_cloud_record_is_not_found(cloud_store):
    from google.api_core.exceptions import NotFound
    cloud_store.download_as_bytes.side_effect = NotFound('absent')
    with pytest.raises(KeyError):
        store.get('region', 'missing')


def test_cloud_failure_does_not_fall_back_to_sqlite(cloud_store, monkeypatch):
    from google.api_core.exceptions import Forbidden
    sqlite = Mock(side_effect=AssertionError('ephemeral fallback'))
    monkeypatch.setattr(store, 'sqlite_connection', sqlite)
    cloud_store.upload_from_string.side_effect = Forbidden('private upstream detail')
    with pytest.raises(RuntimeError, match='Persistent region storage is unavailable'):
        store.put('region', 'id', {'id': 'id'})
    sqlite.assert_not_called()


def test_cloud_requires_persistent_configuration(monkeypatch):
    monkeypatch.delenv('WISPR_DATABASE_URL', raising=False)
    monkeypatch.delenv('WISPR_REGION_BUCKET', raising=False)
    monkeypatch.setenv('K_SERVICE', 'test-service')
    with pytest.raises(RuntimeError, match='no ephemeral database fallback'):
        store.put('region', 'id', {})