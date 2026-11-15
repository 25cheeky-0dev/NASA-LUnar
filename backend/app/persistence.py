"""Content-addressed evidence: local SQLite or private GCS; optional Postgres index.

The exact JSON bytes, not an LLM summary, are authoritative. No source raster is
stored in a database row. A content hash detects corruption on every retrieval.
"""
import hashlib
import json
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def connection():
    path = Path(os.getenv('WISPR_DB_PATH', 'data/wispr.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS evidence (id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_utc TEXT NOT NULL, payload BLOB NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS evidence_kind_created ON evidence(kind, created_utc)')
    return db


def save(value, kind='scenario'):
    data = canonical(value)
    key = hashlib.sha256(data).hexdigest()
    bucket = os.getenv('WISPR_EVIDENCE_BUCKET')
    if bucket:
        from google.cloud import storage
        from google.api_core.exceptions import PreconditionFailed
        blob = storage.Client().bucket(bucket).blob(f'evidence/{key}.json')
        try:
            blob.upload_from_string(data, content_type='application/json', if_generation_match=0, timeout=30)
        except PreconditionFailed:
            if hashlib.sha256(blob.download_as_bytes(timeout=30)).hexdigest() != key:
                raise ValueError('Existing cloud evidence failed integrity validation')
    else:
        with connection() as db:
            db.execute('INSERT OR IGNORE INTO evidence VALUES (?, ?, ?, ?)',
                       (key, kind, datetime.now(UTC).isoformat(), data))
    return key


def read(key):
    if not re.fullmatch(r'[0-9a-f]{64}', key):
        raise KeyError('Invalid evidence ID')
    if os.getenv('WISPR_EVIDENCE_BUCKET'):
        from google.cloud import storage
        from google.api_core.exceptions import NotFound
        try:
            data = storage.Client().bucket(os.environ['WISPR_EVIDENCE_BUCKET']).blob(f'evidence/{key}.json').download_as_bytes(timeout=30)
        except NotFound as exc:
            raise KeyError(key) from exc
    else:
        with connection() as db:
            row = db.execute('SELECT payload FROM evidence WHERE id=?', (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        data = row[0]
    if hashlib.sha256(data).hexdigest() != key:
        raise ValueError('Evidence checksum mismatch')
    return json.loads(data)
