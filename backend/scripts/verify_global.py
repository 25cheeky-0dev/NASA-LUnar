"""Executed real-source demonstrations, benchmarks and scientific audit evidence."""

import argparse
import json
import os
import platform
import threading
import time
from pathlib import Path

import numpy as np
import psutil
from fastapi.testclient import TestClient

from app.main import app
from lunar_global.features import FEATURES, aggregate_pixels, native_terrain
from lunar_global.sources import SourceProduct
from lunar_global.storage import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("../docs/evidence/global"))
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    peak = [0]
    stop = threading.Event()

    def sample():
        while not stop.wait(0.02):
            peak[0] = max(peak[0], psutil.Process().memory_info().rss)

    monitor = threading.Thread(target=sample, daemon=True)
    monitor.start()
    client = TestClient(app)
    prefix = "/api/v1/science/global"

    def request(name, method, path, body=None):
        started = time.perf_counter()
        response = client.request(method, path, json=body)
        elapsed = time.perf_counter() - started
        if response.status_code != 200:
            raise AssertionError(f"{name}: {response.status_code} {response.text[:1000]}")
        result = response.json()
        (args.output / (name + ".json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
        results.append(
            dict(
                name=name,
                method=method,
                path=path,
                seconds=elapsed,
                response_bytes=len(response.content),
                status=200,
            )
        )
        return result

    for label in ("cold", "warm"):
        request("levels-" + label, "GET", prefix + "/levels")
        cell = request("lookup-" + label, "GET", prefix + "/cells/lookup?latitude=-89&longitude=45")
        cid = cell["cell_id"]
        request("neighbors-" + label, "GET", prefix + f"/cells/{cid}/neighbors")
        request("vector-" + label, "GET", prefix + f"/cells/{cid}/vectors")
        request("sources-" + label, "GET", prefix + f"/cells/{cid}/sources")
        request("regional-" + label, "GET", prefix + "/regional/SITE04_R000_C000/crosswalk")
        request(
            "candidates-" + label,
            "POST",
            prefix + "/candidates",
            dict(bbox=[0, -90, 90, -80], limit=10),
        )
        request(
            "similarity-" + label,
            "POST",
            prefix + "/similarity",
            dict(reference_cell_id="MOON:HPX:NESTED:128:12345", accept_unknown_uncertainty=True),
        )
        request(
            "overlap-" + label,
            "POST",
            prefix + "/source-overlap",
            dict(bbox=[0, -90, 90, -80], limit=3),
        )
        request("thermal-" + label, "GET", prefix + f"/cells/{cid}/thermal?local_time_bin=0")
        request("tiles-" + label, "GET", prefix + "/tiles/128/2560")
    if args.live:
        payload = dict(
            cell_ids=["MOON:HPX:NESTED:128:163840", "MOON:HPX:NESTED:128:163841"],
            start_utc="2026-11-15T00:00:00Z",
            end_utc="2026-11-15T02:00:00Z",
            step_minutes=60,
            altitude_km=0,
            minimum_shared_minutes=60,
            filters={"qualities": ["INTERPOLATED_ALTIMETRY_UNCERTAINTY_UNKNOWN"]},
        )
        request("global-nasa-analysis", "POST", prefix + "/analysis", payload)
        payload.update(
            dataset_id="SITE04_NW_ORIGIN_PRESERVED_2KM_100M__tiles_3.0.0",
            cell_ids=["SITE04_R000_C000", "SITE04_R000_C001"],
            original_cell_id="SITE04_R000_C000",
            end_utc="2026-11-22T00:00:00Z",
            filters={"qualities": ["source_lola_count_and_uncertainty_not_supplied"]},
        )
        request("site04-seven-day", "POST", prefix + "/delay", payload)
    root = Path(os.getenv("WISPR_GLOBAL_ROOT", "data/lunar-v1"))
    source = SourceProduct.model_validate_json(
        (root / "source_products/lola/source.json").read_text()
    )
    native = native_terrain(root / "source_products/lola/ldem_4.img", source)
    pixels = np.array([0, 1, 100, 12345, 50000, 100000, 163840, 196607])
    low, high = [aggregate_pixels(pixels, 128, native, q) for q in (16, 32)]
    sensitivity = {k: float(np.max(np.abs(low[k] - high[k]))) for k in FEATURES}
    stop.set()
    monitor.join()
    report = dict(
        hardware=platform.platform(),
        processor=platform.processor(),
        python=platform.python_version(),
        cpu_count=psutil.cpu_count(),
        peak_rss_bytes=peak[0],
        total_disk_bytes=sum(p.stat().st_size for p in root.rglob("*") if p.is_file()),
        input_source_bytes=sum(
            p.stat().st_size for p in (root / "source_products").rglob("*") if p.is_file()
        ),
        quadrature_refinement_max_delta=sensitivity,
        quadrature_note="Eight geographically dispersed validation cells, 256 vs 1024 equal-area samples; not a global uncertainty bound",
        benchmarks=results,
        live_requested=args.live,
        sources={
            str(p.relative_to(root)): sha256(p)
            for p in (root / "source_products").rglob("source.json")
        },
    )
    (args.output / "benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
