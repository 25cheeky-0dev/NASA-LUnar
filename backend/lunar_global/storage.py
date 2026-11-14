"""Immutable, hash-verified Parquet snapshots and bounded DuckDB reads."""

import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .grid import GRID_VERSION, RADIUS_M, batches, cell_id, hpx

_expected_hashes = {}


def verify_path(path, digest):
    if sha256(path) != digest:
        raise ValueError("Snapshot checksum mismatch")
    _expected_hashes[str(Path(path).resolve())] = digest


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path = Path(path)
    content = json.dumps(value, indent=2, sort_keys=True, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)


def build_grid(root, nside):
    import math

    target = Path(root) / "global_grid" / f"nside={nside}"
    if target.exists():
        raise ValueError("Grid snapshot already exists; verify it or choose a new root")
    target.mkdir(parents=True)
    manifest = dict(grid_version=GRID_VERSION, nside=nside, count=int(hpx(nside).npix), files={})
    for batch in batches(nside):
        pixels = batch["pixel"]
        table = pa.table(
            dict(
                **batch,
                cell_id=[cell_id(nside, int(p)) for p in pixels],
                parent_pixel=pixels // 4,
                area_m2=[4 * math.pi * RADIUS_M**2 / hpx(nside).npix] * len(pixels),
            )
        )
        path = target / f"part-{int(pixels[0]):08d}.parquet"
        pq.write_table(table, path, compression="zstd")
        manifest["files"][path.name] = sha256(path)
    write_json(target / "manifest.json", manifest)
    return manifest


def query(paths, where="TRUE", parameters=(), limit=100, offset=0, columns="*", order="pixel"):
    if not 1 <= limit <= 1000 or not 0 <= offset <= 4000000:
        raise ValueError("Pagination outside budget")
    for path in paths:
        expected = _expected_hashes.get(str(Path(path).resolve()))
        if expected is not None:
            verify_path(path, expected)
    # SQL fragments are internal constants, never supplied by callers.
    with duckdb.connect(":memory:") as connection:
        connection.execute("SET memory_limit='256MB'")
        connection.execute("SET threads=2")
        relation = connection.from_parquet([str(p) for p in paths], hive_partitioning=False)
        relation.create_view("records")
        cursor = connection.execute(
            f"SELECT {columns} FROM records WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            [*parameters, limit, offset],
        )
        names = [item[0] for item in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


def verified_files(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    paths = []
    for name, digest in manifest["files"].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or sha256(path) != digest:
            raise ValueError("Snapshot checksum/path validation failed")
        _expected_hashes[str(path)] = digest
        paths.append(path)
    return paths, manifest
