from fastapi.testclient import TestClient

from celestial_engine.__main__ import SAMPLE
from celestial_engine.api import get_service
from celestial_engine.horizons_client import SourceUnavailable
from celestial_engine.schemas import EphemerisRequest


def test_existing_app_includes_router(engine):
    from app.main import app

    app.dependency_overrides[get_service] = lambda: engine
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/celestial/health").json()["horizons_status"] == "NOT_PROBED"
            response = client.post("/api/v1/celestial/ephemeris", json=SAMPLE)
            assert response.status_code == 200
            result = engine.ephemeris(EphemerisRequest(**SAMPLE))
            assert response.json()["records"] == result.model_dump(mode="json")["records"]
            assert (
                client.post(
                    "/api/v1/celestial/ephemeris", json=SAMPLE | {"latitude_deg": -100}
                ).status_code
                == 422
            )
            assert "/api/v1/ephemeris" in client.get("/openapi.json").json()["paths"]
    finally:
        app.dependency_overrides.clear()


def test_api_unavailable(engine, monkeypatch):
    from app.main import app

    def fail(_):
        raise SourceUnavailable("Network unavailable")

    monkeypatch.setattr(engine, "ephemeris", fail)
    app.dependency_overrides[get_service] = lambda: engine
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/celestial/ephemeris", json=SAMPLE)
            assert response.status_code == 503
            assert response.json()["fallback"] == "NONE"
    finally:
        app.dependency_overrides.clear()
