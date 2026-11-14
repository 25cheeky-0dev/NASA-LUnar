"""Release contract checks: generated schema, error paths and source failure semantics."""

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.integration import api
from app.integration.engine import AnalysisEngine
from app.integration.grid import Dataset
from app.main import app
from celestial_engine.celestial_service import CelestialService
from celestial_engine.horizons_client import HorizonsClient
from scripts.export_science_contract import OPENAPI, TYPES, artifacts

ROOT = Path(__file__).parents[2]


def test_generated_contracts_are_current_and_science_routes_typed():
    schema_text, types_text = artifacts()
    assert OPENAPI.read_text(encoding="utf-8") == schema_text
    assert TYPES.read_text(encoding="utf-8") == types_text
    count = 0
    for path, methods in app.openapi()["paths"].items():
        if not path.startswith("/api/v1/science/"):
            continue
        if path.startswith("/api/v1/science/global/"):
            continue  # Additive global routes have their own contract assertions.
        for method, operation in methods.items():
            if method not in ("get", "post"):
                continue
            count += 1
            assert "$ref" in operation["responses"]["200"]["content"]["application/json"]["schema"]
            for code in ("404", "422", "429"):
                assert operation["responses"][code]["content"]["application/json"]["schema"][
                    "$ref"
                ].endswith("/ScienceError")
    assert count == 15


def payload(d):
    return dict(
        dataset_id=d.metadata.dataset_id,
        cell_ids=[d.cells[0].cell_id],
        start_utc="2026-11-15T00:00:00Z",
        end_utc="2026-11-22T00:00:00Z",
        step_minutes=60,
        minimum_shared_minutes=60,
        filters={"qualities": ["source_lola_count_and_uncertainty_not_supplied"]},
    )


def test_science_http_errors_and_cors():
    with TestClient(app) as client:
        absent = client.get("/api/v1/science/scenarios/absent")
        assert absent.status_code == 404
        assert absent.json() == dict(
            error_code="NOT_FOUND",
            detail="Scenario absent or expired; reevaluate",
            missing_fields=[],
        )
        invalid = client.get("/api/v1/science/datasets?limit=1001")
        assert invalid.status_code == 422 and invalid.json()["error_code"] == "INVALID_REQUEST"
        for _ in range(2):
            assert api._gate.acquire(blocking=False)
        try:
            d = Dataset.read(ROOT / "docs/evidence/unified/real_v3_two_cells.json")
            busy = client.post("/api/v1/science/analysis", json=payload(d))
            assert busy.status_code == 429 and busy.json()["error_code"] == "CAPACITY_EXCEEDED"
        finally:
            api._gate.release()
            api._gate.release()
        cors = client.options(
            "/api/v1/science/analysis",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert (
            cors.status_code == 200
            and cors.headers["access-control-allow-origin"] == "http://localhost:5173"
        )
        forbidden = client.options(
            "/api/v1/science/analysis",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in forbidden.headers


def test_source_unavailable_remains_unknown_not_synthetic(tmp_path, monkeypatch):
    d = Dataset.read(ROOT / "docs/evidence/unified/real_v3_two_cells.json")
    registry = SimpleNamespace(datasets={d.metadata.dataset_id: d}, errors=[])
    e = AnalysisEngine(registry, CelestialService(HorizonsClient(tmp_path, offline=True)))
    monkeypatch.setattr(api, "engine", lambda: e)
    with TestClient(app) as client:
        response = client.post("/api/v1/science/analysis", json=payload(d))
        assert response.status_code == 200
        body = response.json()
        assert body["dataset"]["synthetic"] is False
        assert body["results"][0]["status"] == "UNKNOWN"
        assert body["results"][0]["dynamic_vector"] is None
        assert not body["comparison"]["ranked"]
        stored = client.get("/api/v1/science/scenarios/" + body["scenario_id"]).json()
        assert stored["dynamic_vectors"] == []
        assert stored["unevaluated_cell_ids"] == [d.cells[0].cell_id]


def test_real_http_examples_validate_against_response_models():
    import json

    from pydantic import TypeAdapter

    examples = json.loads((ROOT / "docs/evidence/unified/final_api_examples.json").read_text())[
        "examples"
    ]
    for example in examples:
        if example["status_code"] != 200 or example["method"] == "OPTIONS":
            continue
        path = example["path"].split("?")[0]
        route = next(
            route
            for route in api.router.routes
            if route.path_regex.fullmatch(path) and example["method"] in route.methods
        )
        TypeAdapter(route.response_model).validate_python(example["response"])
