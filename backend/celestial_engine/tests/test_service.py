import json

import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from celestial_engine.__main__ import SAMPLE
from celestial_engine.celestial_service import export_result
from celestial_engine.data_validation import EphemerisError
from celestial_engine.schemas import EphemerisRequest


@pytest.mark.parametrize(
    "update",
    [
        {"latitude_deg": -91},
        {"longitude_east_deg": 360},
        {"longitude_east_deg": -1},
        {"latitude_deg": float("nan")},
        {"altitude_km": float("inf")},
        {"altitude_reference": "DEM"},
        {"start_utc": "2026-11-15T00:00:00"},
        {"start_utc": "2026-11-15T00:00:00+05:30"},
        {"start_utc": "2026-11-15T00:00:01Z"},
        {"step_minutes": 0},
        {"step_minutes": True},
        {"step_minutes": 2.5},
        {"end_utc": SAMPLE["start_utc"]},
        {"end_utc": "2027-01-01T00:00:00Z"},
        {"step_minutes": 59},
        {"step_minutes": 1, "end_utc": "2026-11-23T00:00:00Z"},
    ],
)
def test_invalid_input(update):
    with pytest.raises(ValidationError):
        EphemerisRequest(**(SAMPLE | update))


@pytest.mark.parametrize("lat,lon", [(-90, 0), (90, 359.999), (-89, 45)])
def test_valid_coordinates(lat, lon):
    assert EphemerisRequest(**(SAMPLE | dict(latitude_deg=lat, longitude_east_deg=lon)))


def test_alignment_and_serialization(engine, request_model, tmp_path):
    result = engine.ephemeris(request_model)
    assert len(result.records) == 169 and all(row.valid for row in result.records)
    assert result.metadata["target_timestamp_sets_match"]
    export_result(result, tmp_path)
    data = json.loads((tmp_path / "sample_ephemeris.json").read_text())
    table = pq.read_table(tmp_path / "sample_ephemeris.parquet")
    assert table.num_rows == 169
    assert str(table.schema.field("timestamp_utc").type) == "timestamp[us, tz=UTC]"
    assert table.column("sun_elevation_deg").to_pylist() == [
        row.sun_elevation_deg for row in result.records
    ]
    assert data["records"][0]["timestamp_utc"].endswith("Z")
    assert json.loads(table.schema.metadata[b"wispr_metadata"]) == result.metadata


def test_timestamp_gaps_are_explicit(engine, request_model, monkeypatch):
    original = engine.client.target

    def target(target, request):
        records, meta = original(target, request)
        if target == 399:
            records.pop(request.timestamps()[1])
        return records, meta

    monkeypatch.setattr(engine.client, "target", target)
    result = engine.ephemeris(request_model)
    assert len(result.records) == 169
    assert result.records[1].earth_elevation_deg is None
    assert result.records[1].sun_elevation_deg is not None
    assert not result.records[1].valid
    assert result.metadata["missing_observations"] == 1
    assert not result.metadata["target_timestamp_sets_match"]


def test_off_cadence_rejected(engine, request_model, monkeypatch):
    original = engine.client.target

    def target(target, request):
        from datetime import timedelta

        records, meta = original(target, request)
        records[request.start_utc + timedelta(minutes=1)] = (
            0,
            0,
        )  # Synthetic corruption test.
        return records, meta

    monkeypatch.setattr(engine.client, "target", target)
    with pytest.raises(EphemerisError):
        engine.ephemeris(request_model)
