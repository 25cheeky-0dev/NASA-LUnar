"""Persistent identities/jobs: SQLite locally, PostgreSQL in shared deployments."""
import json
import os
from contextlib import contextmanager
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
            raise RuntimeError('Persistent region jobs on Cloud Run require WISPR_DATABASE_URL; no ephemeral database fallback')
        with sqlite_connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS region_objects (kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,id))')
            yield db,'?'


def put(kind,key,value):
    payload=json.dumps(value,sort_keys=True,allow_nan=False)
    with database() as (db,p):
        db.execute(f'INSERT INTO region_objects(kind,id,payload) VALUES ({p},{p},{p}) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload',(kind,key,payload))


def get(kind,key):
    with database() as (db,p):
        row=db.execute(f'SELECT payload FROM region_objects WHERE kind={p} AND id={p}',(kind,key)).fetchone()
    if not row:raise KeyError(key)
    return json.loads(row[0])
