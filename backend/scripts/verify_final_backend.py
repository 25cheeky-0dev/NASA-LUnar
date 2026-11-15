"""Full real-data backend workflow over TCP, without frontend or rendering."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[2]


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
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
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        **options,
    )
    evidence = []
    output = ROOT / "docs/evidence/final-backend"
    output.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=180) as client:
            for _ in range(100):
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(0.1)

            def call(name, method, path, body=None, status=200):
                start = time.perf_counter()
                response = client.request(method, "/api/v1/science" + path, json=body)
                assert response.status_code == status, (
                    name,
                    response.status_code,
                    response.text[:3000],
                )
                data = response.json()
                evidence.append(
                    dict(
                        name=name,
                        method=method,
                        path=path,
                        request=body,
                        status=status,
                        elapsed_seconds=time.perf_counter() - start,
                        server_rss_bytes=sum(
                            p.memory_info().rss
                            for p in [
                                psutil.Process(process.pid),
                                *psutil.Process(process.pid).children(recursive=True),
                            ]
                        ),
                        response=data,
                    )
                )
                return data

            call("status", "GET", "/status")
            call(
                "thermal-region",
                "GET",
                "/global/thermal-observations?west=44&south=-90&east=46&north=-88&local_time_bin=0&channel=tbol",
            )
            call("levels", "GET", "/global/levels")
            cell = call("lookup", "GET", "/global/cells/lookup?latitude=-89&longitude=45")
            cid = cell["cell_id"]
            call("terrain", "GET", f"/global/cells/{cid}/features")
            call("physical-vector", "GET", f"/global/cells/{cid}/vectors")
            call(
                "similarity",
                "POST",
                "/global/similarity",
                dict(reference_cell_id=cid, accept_unknown_uncertainty=True, maximum_results=5),
            )
            call("sources", "GET", f"/global/cells/{cid}/sources")
            call("thermal", "GET", f"/global/cells/{cid}/thermal?local_time_bin=0")
            call("crosswalk", "GET", "/global/regional/SITE04_R000_C000/crosswalk")
            ds = call("datasets", "GET", "/datasets")["datasets"][0]["dataset_id"]
            native = call("native", "GET", f"/datasets/{ds}/cells/SITE04_R000_C000")
            assert native["cell"]["elevation_m"] == 1072.0976434326171
            model = call("fit", "POST", "/representations/fit", dict(dataset_id=ds, dimensions=2))[
                "metadata"
            ]
            model_id = model["model_sha256"]
            for space in [
                "physical-scales-v1",
                "terrain-population-zscore-v1",
                "PCA_FEATURE_EMBEDDING",
            ]:
                call(
                    space,
                    "POST",
                    "/representations/search",
                    dict(
                        dataset_id=ds,
                        model_id=model_id,
                        cell_id="SITE04_R000_C000",
                        space=space,
                        accept_descriptive_similarity=True,
                        limit=5,
                    ),
                )
            call(
                "strict-uncertainty",
                "GET",
                f"/datasets/{ds}/similarity/SITE04_R000_C000",
                status=422,
            )
            call(
                "descriptive",
                "GET",
                f"/datasets/{ds}/similarity/SITE04_R000_C000?accept_unknown_uncertainty=true&limit=5",
            )
            horizon = call(
                "horizon",
                "POST",
                "/terrain/horizon",
                dict(
                    dataset_id=ds,
                    cell_id="SITE04_R000_C000",
                    azimuths_deg=[0, 45.123456, 90, 180, 270],
                ),
            )
            assert (
                not horizon["observer_reference_compatible"] and not horizon["far_field_complete"]
            )
            scenario = dict(
                dataset_id=ds,
                cell_ids=["SITE04_R000_C000", "SITE04_R000_C001"],
                start_utc="2026-11-15T00:00:00Z",
                end_utc="2026-11-22T00:00:00Z",
                step_minutes=60,
                minimum_shared_minutes=120,
                filters=dict(qualities=["source_lola_count_and_uncertainty_not_supplied"]),
            )
            call("analysis", "POST", "/analysis", scenario)
            delay = call(
                "delay", "POST", "/delay", dict(scenario, original_cell_id="SITE04_R000_C000")
            )
            assert delay["outcome"] in (
                "KEEP",
                "SWITCH",
                "NO_QUALIFYING_MODELED_OPTION",
                "INSUFFICIENT_DATA",
            )
            # The same actual cells with partial terrain must not be ranked as visible.
            partial = call(
                "terrain-analysis",
                "POST",
                "/analysis",
                dict(scenario, horizon_model="TERRAIN_PARTIAL", terrain_site_id="SITE04"),
            )
            assert not partial["comparison"]["ranked"]
            assert all(r["dynamic_vector"]["missing_data"] for r in partial["results"])
            assert client.get("/openapi.json").json() == json.loads(
                (ROOT / "docs/contracts/science.openapi.json").read_text()
            )
        (output / "workflow.json").write_text(
            json.dumps(
                dict(transport="Actual uvicorn TCP HTTP", examples=evidence), allow_nan=False
            )
        )
        print(
            json.dumps(
                dict(
                    http_calls=len(evidence),
                    model_id=model_id,
                    outcome=delay["outcome"],
                    max_server_rss_bytes=max(x["server_rss_bytes"] for x in evidence),
                )
            )
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    main()
