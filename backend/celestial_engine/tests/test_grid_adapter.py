"""Synthetic grid interface tests only; these do not validate lunar terrain."""

import json

import pytest
from pydantic import ValidationError

from celestial_engine.grid_adapter import GridAdapter, GridMetadata, read_grid

META = dict(
    coordinate_frame="MOON_ME_DE421",
    longitude_convention="east_positive_0_360",
    latitude_type="planetodetic",
    elevation_units="m",
    elevation_datum="unverified_DEM",
    source="SYNTHETIC_INTERFACE_TEST_ONLY",
)
CELL = dict(
    cell_id="original:id-A",
    latitude_deg=-89,
    longitude_east_deg=45,
    elevation_m=100,
    slope_deg=2,
    roughness_m=1,
    valid=True,
    extra_field="preserved",
)


def test_ids_and_alignment(engine, request_model):
    result = GridAdapter(engine).process(
        [CELL, CELL | dict(cell_id="invalid", valid=False)], META, request_model
    )
    assert result["results"][0]["cell_id"] == CELL["cell_id"]
    assert result["skipped_cell_ids"] == ["invalid"]
    assert not result["results"][0]["grid_elevation_applied"]
    assert all(row.altitude_km == 0 for row in result["results"][0]["ephemeris"].records)


@pytest.mark.parametrize(
    "change",
    [
        {"coordinate_frame": "Earth"},
        {"elevation_units": "km"},
        {"longitude_convention": "west_positive"},
        {"elevation_datum": ""},
    ],
)
def test_metadata_rejected(change):
    with pytest.raises(ValidationError):
        GridMetadata(**(META | change))


def test_job_budgets_and_datum_before_network(engine, request_model, monkeypatch):
    def forbidden(_):
        raise AssertionError("No requests allowed before validation")

    monkeypatch.setattr(engine, "ephemeris", forbidden)
    adapter = GridAdapter(engine, max_cells=2, max_samples=200)
    for cells, options in [
        ([CELL] * 3, {}),
        ([CELL] * 2, {}),
        ([CELL], {"use_grid_elevation": True}),
        ([CELL], {"batch_size": 3}),
        ([CELL | {"latitude_deg": -91}], {}),
    ]:
        with pytest.raises((ValueError, ValidationError)):
            adapter.process(cells, META, request_model, **options)
    with pytest.raises(ValueError, match="sample budget"):
        adapter.process([CELL, CELL | {"cell_id": "B"}], META, request_model, batch_size=2)


def test_explicit_verified_height_conversion(engine, request_model, monkeypatch):
    captured = []

    def capture(request):
        captured.append(request)

    monkeypatch.setattr(engine, "ephemeris", capture)
    meta = META | dict(
        elevation_datum="horizons_lunar_reference",
        elevation_matches_horizons_reference=True,
    )
    cells = [CELL | dict(cell_id=f"test-{i}") for i in range(3)]
    result = GridAdapter(engine).process(
        cells, meta, request_model, use_grid_elevation=True, batch_size=2
    )
    assert [r["cell_id"] for r in result["results"]] == [cell["cell_id"] for cell in cells]
    assert all(request.altitude_km == 0.1 for request in captured)
    assert all(request.timestamps() == request_model.timestamps() for request in captured)


def test_json_grid_read(tmp_path):
    path = tmp_path / "grid.json"
    path.write_text(json.dumps(dict(metadata=META, cells=[CELL])))
    metadata, cells = read_grid(path)
    assert cells[0].cell_id == CELL["cell_id"]
    assert metadata.source == "SYNTHETIC_INTERFACE_TEST_ONLY"


def test_parquet_grid_read(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pylist([CELL]).replace_schema_metadata(
        {b"wispr_grid_metadata": json.dumps(META).encode()}
    )
    path = tmp_path / "grid.parquet"
    pq.write_table(table, path)
    assert read_grid(path)[1][0].cell_id == CELL["cell_id"]
