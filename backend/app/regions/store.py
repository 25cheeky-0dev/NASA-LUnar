"""Persistent identities/jobs: SQLite locally, PostgreSQL or private GCS in cloud."""
import hashlib
import json
import os
import re
from contextlib import contextmanager
from functools import lru_cache
from app.persistence import connection as sqlite_connection


@contextmanager
def database():
    url=os.getenv('WISPR_DATABASE_URL')
    if url:
        import psycopg
        with psycopg.connect(url,connect_timeout=10) as db:
            db.execute('CREATE TABLE IF NOT EXISTS region_objects (kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,id))')
            yield db,'%s'
    else:
        if os.getenv('K_SERVICE'):
            raise RuntimeError('Persistent region jobs on Cloud Run require WISPR_DATABASE_URL or WISPR_REGION_BUCKET; no ephemeral database fallback')
        with sqlite_connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS region_objects (kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,id))')
            yield db,'?'

@lru_cache(maxsize=1)
def cloud_client():
    from google.cloud import storage
    return storage.Client()


def cloud_blob(kind, key):
    # Hash both identity fields; user-supplied IDs cannot escape this prefix.
    identity = json.dumps([kind, key], separators=(',', ':')).encode()
    digest = hashlib.sha256(identity).hexdigest()
    return cloud_client().bucket(os.environ['WISPR_REGION_BUCKET']).blob(
        f'region-state/{digest}.json')


def use_cloud_objects():
    return not os.getenv('WISPR_DATABASE_URL') and bool(os.getenv('WISPR_REGION_BUCKET'))

def put(kind,key,value):
    payload=json.dumps(value,sort_keys=True,allow_nan=False)
    if use_cloud_objects():
        from google.api_core.exceptions import GoogleAPICallError
        try:
            blob = cloud_blob(kind, key)
            blob.metadata = {'kind': kind, 'key': key}
            blob.upload_from_string(
                payload, content_type='application/json', timeout=30)
        except GoogleAPICallError as exc:
            raise RuntimeError('Persistent region storage is unavailable') from exc
        return
    with database() as (db,p):
        db.execute(f'INSERT INTO region_objects(kind,id,payload) VALUES ({p},{p},{p}) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload',(kind,key,payload))


def get(kind,key):
    if use_cloud_objects():
        from google.api_core.exceptions import GoogleAPICallError, NotFound
        try:
            data = cloud_blob(kind, key).download_as_bytes(timeout=30)
        except NotFound as exc:
            raise KeyError(key) from exc
        except GoogleAPICallError as exc:
            raise RuntimeError('Persistent region storage is unavailable') from exc
        return json.loads(data)
    with database() as (db,p):
        row=db.execute(f'SELECT payload FROM region_objects WHERE kind={p} AND id={p}',(kind,key)).fetchone()
    if not row:raise KeyError(key)
    return json.loads(row[0])


def records(kind, limit=200):
    """Bounded catalog reads, including region objects written before metadata."""
    if use_cloud_objects():
        result=[]
        for blob in cloud_client().list_blobs(os.environ['WISPR_REGION_BUCKET'], prefix='region-state/', max_results=1000, timeout=30):
            if not re.fullmatch(r'region-state/[0-9a-f]{64}\.json',blob.name):
                continue
            meta=blob.metadata or {}
            if meta.get('kind') and meta['kind'] != kind:
                continue
            if not meta and kind != 'region':
                continue
            value=json.loads(blob.download_as_bytes(timeout=30))
            key=meta.get('key')
            if not key and kind == 'region' and 'geometry' in value:
                key=value.get('region_id')
            if key and cloud_blob(kind,key).name == blob.name:
                result.append((key,value))
            if len(result)>=limit:
                break
        return sorted(result)
    with database() as (db,p):
        rows=db.execute(f'SELECT id,payload FROM region_objects WHERE kind={p} ORDER BY id LIMIT {p}',(kind,limit)).fetchall()
    return [(key,json.loads(value)) for key,value in rows]
