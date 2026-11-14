"""Build bounded whole-Moon grid snapshots and preserved Site04 crosswalks."""

import argparse
import json
import platform
import threading
import time
from pathlib import Path

import psutil
import pyarrow as pa
import pyarrow.parquet as pq

from app.integration.v3 import read_v3
from lunar_global.regions import crosswalk
from lunar_global.storage import build_grid, sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/lunar-v1"))
    parser.add_argument("--v3", type=Path, required=True)
    parser.add_argument("--levels", type=int, nargs="+", default=[64, 128, 256])
    args = parser.parse_args()
    peak = [0]
    stop = threading.Event()

    def sample():
        while not stop.wait(0.05):
            peak[0] = max(peak[0], psutil.Process().memory_info().rss)

    monitor = threading.Thread(target=sample, daemon=True)
    monitor.start()
    result = dict(
        hardware=platform.platform(),
        processor=platform.processor(),
        cpu_count=psutil.cpu_count(),
        total_memory_bytes=psutil.virtual_memory().total,
        python=platform.python_version(),
        cache="first build",
        levels=[],
    )
    dataset = read_v3(args.v3)
    for nside in args.levels:
        start = time.perf_counter()
        manifest = build_grid(args.root, nside)
        build_seconds = time.perf_counter() - start
        start = time.perf_counter()
        rows = crosswalk(dataset, nside)
        path = args.root / "crosswalk" / f"nside-{nside}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise ValueError("Crosswalk snapshot already exists")
        pq.write_table(pa.Table.from_pylist(rows), path)
        result["levels"].append(
            dict(
                nside=nside,
                cells=manifest["count"],
                grid_build_seconds=build_seconds,
                crosswalk_seconds=time.perf_counter() - start,
                crosswalk_rows=len(rows),
                crosswalk_sha256=sha256(path),
            )
        )
    stop.set()
    monitor.join()
    result.update(
        peak_rss_bytes=peak[0],
        disk_bytes=sum(p.stat().st_size for p in args.root.rglob("*") if p.is_file()),
        preserved_regional_cells=len(dataset.cells),
        regional_dataset_sha256=dataset.digest,
    )
    write_json(args.root / "grid-benchmark.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
