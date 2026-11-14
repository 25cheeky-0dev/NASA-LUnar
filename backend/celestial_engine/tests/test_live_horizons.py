"""Opt-in real network integration, never run as an offline unit test."""

import json
import os
from datetime import timedelta

import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from celestial_engine.__main__ import SAMPLE
from celestial_engine.api import get_service
from celestial_engine.celestial_service import CelestialService, export_result
from celestial_engine.horizons_client import HorizonsClient
from celestial_engine.schemas import EphemerisRequest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("WISPR_LIVE_TEST") != "1",
        reason="Set WISPR_LIVE_TEST=1 for NASA access",
    ),
]


def test_live_requested_week(tmp_path):
    from app.main import app

    request = EphemerisRequest(**SAMPLE)
    engine = CelestialService(HorizonsClient(tmp_path / "raw"))
    result = engine.ephemeris(request)
    assert len(result.records) == 169
    assert all(row.valid for row in result.records)
    assert result.metadata["target_timestamp_sets_match"]
    assert all(q["delivery"] == "LIVE" for q in result.metadata["queries"].values())
    for body in ("sun", "earth"):
        az = [getattr(row, f"{body}_azimuth_deg") for row in result.records]
        el = [getattr(row, f"{body}_elevation_deg") for row in result.records]
        # Loose diagnostics for THIS hourly polar sample, not universal lunar bounds.
        assert max(abs((b - a + 180) % 360 - 180) for a, b in zip(az, az[1:])) < 5
        assert max(abs(b - a) for a, b in zip(el, el[1:])) < 1
    export_result(result, tmp_path / "exports")
    assert pq.read_table(tmp_path / "exports/sample_ephemeris.parquet").num_rows == 169
    assert (
        len(json.loads((tmp_path / "exports/sample_ephemeris.json").read_text())["records"]) == 169
    )
    app.dependency_overrides[get_service] = lambda: engine
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/celestial/ephemeris", json=SAMPLE)
            assert response.status_code == 200
            assert response.json()["records"] == result.model_dump(mode="json")["records"]
    finally:
        app.dependency_overrides.clear()
    # Independently parameterized, shorter interval at a selected timestamp.
    selected = request.model_copy(
        update={
            "start_utc": request.start_utc + timedelta(hours=84),
            "end_utc": request.start_utc + timedelta(hours=85),
        }
    )
    comparison = engine.ephemeris(selected)
    for actual, expected in zip(comparison.records, result.records[84:86], strict=True):
        assert actual == expected
    output = os.getenv("CELESTIAL_LIVE_OUTPUT")
    if output:
        export_result(result, output)
