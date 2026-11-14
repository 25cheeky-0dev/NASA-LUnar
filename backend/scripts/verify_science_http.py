"""Exercise a real TCP FastAPI server against WISPR_GRID_DIR; save exact HTTP examples."""

import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]


def polygon_wkb(value):
    endian = "<" if value[0] == 1 else ">"
    kind, rings = struct.unpack_from(endian + "II", value, 1)
    assert kind == 3 and rings == 1
    count = struct.unpack_from(endian + "I", value, 9)[0]
    return [list(struct.unpack_from(endian + "dd", value, 13 + 16 * i)) for i in range(count)]


def verify():
    grid_root = Path(os.environ["WISPR_GRID_DIR"])
    hashes = json.loads((grid_root / "SHA256_MANIFEST.json").read_text())["files"]
    for name, expected in hashes.items():
        with (grid_root / name).open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == expected, name
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["CORS_ORIGINS"] = "http://localhost:5173,http://127.0.0.1:5173"
    # Popen has no console window on Windows; the helper owns and stops this server.
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT / "backend",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        **options,
    )
    entries = []
    try:
        with httpx.Client(base_url=base, timeout=180) as client:
            for _ in range(100):
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                if process.poll() is not None:
                    raise RuntimeError(process.stderr.read().decode())
                time.sleep(0.1)
            else:
                raise RuntimeError("Server did not start")

            def call(name, method, path, body=None, expected=200, headers=None, record=True):
                response = client.request(method, path, json=body, headers=headers)
                assert response.status_code == expected, (
                    name,
                    response.status_code,
                    response.text[:1000],
                )
                result = (
                    response.json()
                    if response.headers.get("content-type", "").startswith("application/json")
                    else response.text
                )
                entries.append(
                    dict(
                        name=name,
                        method=method,
                        path=path,
                        request_body=body,
                        request_headers=headers or {},
                        status_code=response.status_code,
                        response_headers={
                            k: v
                            for k, v in response.headers.items()
                            if k
                            in (
                                "content-type",
                                "access-control-allow-origin",
                                "access-control-allow-methods",
                            )
                        },
                        response=result,
                    )
                )
                if not record:
                    entries.pop()
                return result

            discovery = call("datasets", "GET", "/api/v1/science/datasets?offset=0&limit=100")
            assert not discovery["ingestion_errors"]
            d = next(
                d for d in discovery["datasets"] if d["region"] == "Site04" and not d["synthetic"]
            )
            assert (
                d["cell_count"] == 400
                and d["grid_version"] == "2.0.0"
                and d["processing_version"] == "3.0.0"
            )
            prefix = "/api/v1/science/datasets/" + d["dataset_id"]
            all_cells = []
            for offset in (0, 137, 274):
                page = call(
                    f"cells_page_{offset}",
                    "GET",
                    prefix + f"/cells?offset={offset}&limit=137",
                    record=False,
                )
                assert page["total"] == 400
                all_cells.extend(page["cells"])
            call("cells_page", "GET", prefix + "/cells?offset=0&limit=2")
            baseline = {
                row["cell_id"]: row
                for row in pq.read_table(grid_root / "baseline/grid.parquet").to_pylist()
            }
            geometry = {
                row["cell_id"]: row
                for row in pq.read_table(grid_root / "baseline/grid_geometry.parquet").to_pylist()
            }
            assert len(all_cells) == 400 and {c["cell_id"] for c in all_cells} == set(baseline)
            for cell in all_cells:
                original = baseline[cell["cell_id"]]
                for field in (
                    "latitude",
                    "longitude",
                    "x_m",
                    "y_m",
                    "elevation_m",
                    "slope_deg",
                    "roughness_m",
                ):
                    assert cell[field] == original[field]
                shape = geometry[cell["cell_id"]]["geometry_wkb"]
                assert cell["original_geometry_wkb_hex"] == shape.hex()
                assert cell["geometry"]["coordinates"] == [polygon_wkb(shape)]
                assert cell["geometry"]["crs"] == d["projected_crs"]
                assert cell["uncertainty"] == dict(
                    elevation_uncertainty_m=None, lola_shot_count=None
                )
            ids = ["SITE04_R000_C000", "SITE04_R000_C001"]
            call("cell", "GET", prefix + "/cells/" + ids[0])
            vector = call("static_vector", "GET", prefix + "/vectors/" + ids[0])
            assert vector["feature_names"] == ["elevation_m", "slope_deg", "roughness_m"]
            assert vector["raw"] == [baseline[ids[0]][key] for key in vector["feature_names"]]
            assert vector["normalized"] == [
                x / y for x, y in zip(vector["raw"], [1000, 10, 10], strict=True)
            ]
            quality = "source_lola_count_and_uncertainty_not_supplied"
            selected = call(
                "candidates", "POST", prefix + "/candidates", {"qualities": [quality], "limit": 2}
            )
            assert selected["cell_ids"] == ids and selected["total"] == 400
            call(
                "similarity_quality_rejection",
                "GET",
                prefix + "/similarity/" + ids[0],
                expected=422,
            )
            scenario = dict(
                dataset_id=d["dataset_id"],
                cell_ids=ids,
                start_utc="2026-11-15T00:00:00Z",
                end_utc="2026-11-22T00:00:00Z",
                step_minutes=60,
                minimum_shared_minutes=60,
                altitude_km=0,
                horizon_model="GEOMETRIC_IDEAL",
                filters={"qualities": [quality]},
            )
            combined = call("analysis", "POST", "/api/v1/science/analysis", scenario)
            call("celestial", "POST", "/api/v1/science/celestial", scenario | {"cell_ids": ids[:1]})
            call("dynamic_vectors", "GET", "/api/v1/science/scenarios/" + combined["scenario_id"])
            call("ranking", "POST", "/api/v1/science/ranking", scenario)
            delay = call(
                "delay", "POST", "/api/v1/science/delay", scenario | {"original_cell_id": ids[0]}
            )
            assert delay["outcome"] == "KEEP"
            measurements = {}
            for phase, expected in [("original", 5989), ("delayed", 10080)]:
                measurements[phase] = []
                for row in delay[phase]["results"]:
                    dynamic = row["dynamic_vector"]
                    assert dynamic["horizon_model"] == "GEOMETRIC_IDEAL"
                    assert dynamic["observer"]["altitude_km"] == 0
                    assert dynamic["features"]["terrain_clearance_supported"] is False
                    assert dynamic["features"]["unknown_data_fraction"] == 0
                    longest = dynamic["features"]["longest_shared_minutes"]
                    assert abs(longest - expected) < 1, (phase, longest)
                    assert len(dynamic["records"]) == 169
                    assert all(
                        q["delivery"] in ("LIVE", "VERIFIED_CACHE")
                        for q in dynamic["provenance"]["queries"].values()
                    )
                    measurements[phase].append(
                        dict(
                            cell_id=row["cell_id"],
                            longest_shared_minutes=longest,
                            delivery={
                                b: q["delivery"]
                                for b, q in dynamic["provenance"]["queries"].items()
                            },
                        )
                    )
            call("missing_cell", "GET", prefix + "/cells/not-a-cell", expected=404)
            call("expired_scenario", "GET", "/api/v1/science/scenarios/absent", expected=404)
            call("invalid_pagination", "GET", prefix + "/cells?limit=1001", expected=422)
            call(
                "invalid_utc",
                "POST",
                "/api/v1/science/analysis",
                scenario | {"start_utc": "2026-11-15T00:00:00"},
                expected=422,
            )
            call(
                "cors",
                "OPTIONS",
                "/api/v1/science/analysis",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            assert (
                entries[-1]["response_headers"]["access-control-allow-origin"]
                == "http://localhost:5173"
            )
            exported = json.loads((ROOT / "docs/contracts/science.openapi.json").read_text())
            assert client.get("/openapi.json").json() == exported
        output = dict(
            transport="Actual localhost TCP HTTP against a subprocess uvicorn server",
            source="Real native V3 package and validated NASA Horizons live/cache responses; no synthetic fallback",
            dataset_id=d["dataset_id"],
            cell_count=len(all_cells),
            verified_package_file_count=len(hashes),
            measurements=measurements,
            outcome=delay["outcome"],
            examples=entries,
        )
        path = ROOT / "docs/evidence/unified/final_api_examples.json"
        path.write_text(json.dumps(output, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in output.items() if k != "examples"}, indent=2))
        print(f"{len(entries)} actual HTTP examples saved")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    verify()
