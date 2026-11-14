"""Atomic, content-checked exact-query disk cache. Raw NASA bytes are retained."""

import hashlib
import json
import os
import tempfile
from pathlib import Path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic_write(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(raw)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


class QueryCache:
    def __init__(self, root):
        self.root = Path(root)

    def key(self, params):
        return digest(json.dumps(params, sort_keys=True).encode())

    def get(self, params):
        try:
            entry = json.loads((self.root / (self.key(params) + ".json")).read_bytes())
            raw = entry["raw"].encode()
            meta = entry["metadata"]
            if meta["query_parameters"] == params and meta["raw_sha256"] == digest(raw):
                return raw, meta
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
        return None

    def put(self, params, raw, metadata):
        entry = dict(raw=raw.decode("utf-8"), metadata=metadata)
        atomic_write(
            self.root / (self.key(params) + ".json"),
            json.dumps(entry, indent=2).encode(),
        )
