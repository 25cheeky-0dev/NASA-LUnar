"""Synthetic interface tests; these are NOT validation of Narinder's V3 data."""

import json
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.integration import api
from app.integration.engine import AnalysisEngine, Scenario, visibility
from app.integration.grid import Dataset, Filters, Registry
from app.main import app
from celestial_engine.schemas import EphemerisResult, Observation


@pytest.fixture
def payload():
    return dict(
        metadata=dict(
            dataset_id="synthetic-site04-v3",
            grid_version="V3-SYNTHETIC",
            scope="REGIONAL",
            coordinate_frame="MOON_ME_DE421",
            latitude_type="planetodetic",
            longitude_convention="east_positive_-180_180",
            elevation_datum="synthetic",
            source={"kind": "SYNTHETIC_FIXTURE_NOT_NASA", "source_id": "synthetic-source"},
            terrain_definition="synthetic standard deviation",
            resolution_m=5,
            region="Site04",
            synthetic=True,
            projected_crs="synthetic",
        ),
        cells=[
            dict(
                cell_id=f"SYNTHETIC-Site04-{i:03d}",
                latitude_deg=-89.0,
                longitude_deg=-45.0 + i,
                projected_x=123.456 + i,
                projected_y=-987.654,
                elevation_m=1000.0 + i,
                slope_deg=5.0,
                roughness_m=2.0,
                valid=True,
                coverage_fraction=1.0,
                quality="VERIFIED",
                uncertainty={
                    "schema": "measurement-standard-uncertainty-v1",
                    "source_id": "synthetic-source",
                    "terrain_definition": "synthetic standard deviation",
                    "citation": "Synthetic test fixture only",
                    "measurements": {
                        name: {"unit": unit, "standard_uncertainty": 1.0}
                        for name, unit in [
                            ("elevation_m", "m"),
                            ("slope_deg", "degree"),
                            ("roughness_m", "m"),
                        ]
                    },
                },
                neighbors=[],
                geometry={"type": "Point", "coordinates": [-45.0 + i, -89.0]},
            )
            for i in range(3)
        ],
    )


@pytest.fixture
def dataset(payload):
    return Dataset(payload["metadata"], payload["cells"], "synthetic-sha")


class FakeCelestial:
    def __init__(self, elevations=None, missing=False):
        self.requests = []
        self.elevations = elevations or (lambda request: 10.0)
        self.missing = missing

    def ephemeris(self, request):
        self.requests.append(request)
        el = self.elevations(request)
        records = [
            Observation(
                timestamp_utc=t,
                sun_azimuth_deg=10.0,
                sun_elevation_deg=el,
                earth_azimuth_deg=20.0,
                earth_elevation_deg=el,
                latitude_deg=request.latitude_deg,
                longitude_east_deg=request.longitude_east_deg,
                altitude_km=request.altitude_km,
                valid=True,
                quality="SOURCE_BACKED",
            )
            for t in request.timestamps()
        ]
        if self.missing:
            records = records[1:]
        return EphemerisResult(records=records, metadata={"source": "SYNTHETIC_TEST_DOUBLE"})


def request(dataset, **kwargs):
    return Scenario(
        dataset_id=dataset.metadata.dataset_id,
        cell_ids=[c.cell_id for c in dataset.cells[:16]],
        start_utc="2026-11-15T00:00:00Z",
        end_utc="2026-11-15T03:00:00Z",
        step_minutes=60,
        minimum_shared_minutes=120,
        **kwargs,
    )


def engine(dataset, celestial=None):
    return AnalysisEngine(
        SimpleNamespace(datasets={dataset.metadata.dataset_id: dataset}),
        celestial or FakeCelestial(),
    )


def test_json_parquet_preservation(tmp_path, payload):
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "grid.json"
    path.write_text(json.dumps(payload))
    json_grid = Dataset.read(path)
    table = pa.Table.from_pylist(payload["cells"]).replace_schema_metadata(
        {b"wispr_grid_metadata": json.dumps(payload["metadata"]).encode()}
    )
    pq.write_table(table, tmp_path / "grid.parquet")
    parquet_grid = Dataset.read(tmp_path / "grid.parquet")
    assert json_grid.cells == parquet_grid.cells
    assert json_grid.cells[0].cell_id == "SYNTHETIC-Site04-000"
    assert json_grid.cells[0].longitude_deg == -45
    assert json_grid.cells[0].projected_x == 123.456
    assert json_grid.east_longitude(json_grid.cells[0]) == 315


@pytest.mark.parametrize("size,version", [(0, "V4"), (1, "V3"), (437, "V4")])
def test_arbitrary_sizes(payload, size, version):
    payload["metadata"]["grid_version"] = version
    cells = [payload["cells"][0] | {"cell_id": str(i)} for i in range(size)]
    d = Dataset(payload["metadata"], cells, "x")
    assert d.raw.shape == (size, 3)
    assert d.select(Filters())[0]["total"] == size


def test_vectors_and_missing(dataset, payload):
    v = dataset.vector(dataset.cells[0].cell_id)
    assert v["raw"] == [1000, 5, 2]
    assert v["normalized"] == [1, 0.5, 0.2]
    assert dataset.vector(dataset.cells[0].cell_id) == v
    payload["cells"][0]["roughness_m"] = None
    d = Dataset(payload["metadata"], payload["cells"], "x")
    assert d.vector(d.cells[0].cell_id)["missing_mask"] == [False, False, True]
    assert d.vector(d.cells[0].cell_id)["normalized"][2] is None
    assert d.select(Filters())[0]["total"] == 2
    assert dataset.select(Filters(maximum_slope_deg=4))[0]["total"] == 0
    assert dataset.select(Filters(limit=1, offset=1))[0]["cell_ids"] == [dataset.cells[1].cell_id]


def test_similarity_excludes_resolution_uncertainty(dataset):
    assert len(dataset.similarity(dataset.cells[0].cell_id)["matches"]) == 2
    dataset.cells[1].resolution_m = 100
    dataset.cells[2].uncertainty = {"kind": "different"}
    assert dataset.similarity(dataset.cells[0].cell_id)["matches"] == []


def test_duplicate_and_invalid_coordinates(payload):
    with pytest.raises(ValueError):
        Dataset(payload["metadata"], payload["cells"] * 2, "x")
    payload["metadata"]["longitude_convention"] = "west_positive_0_360"
    with pytest.raises(ValueError):
        Dataset(payload["metadata"], payload["cells"], "x")
    for cell in payload["cells"]:
        cell["longitude_deg"] = 45
    d = Dataset(payload["metadata"], payload["cells"], "x")
    assert d.east_longitude(d.cells[0]) == 315


def test_combined_alignment_and_separation(dataset):
    e = engine(dataset)
    result = e.analyze(request(dataset))
    assert len(result["comparison"]["ranked"]) == 3
    for row, req in zip(result["results"], e.celestial.requests):
        dynamic = row["dynamic_vector"]
        assert req.altitude_km == 0  # never DEM mean elevation
        assert req.longitude_east_deg == (row["cell"]["longitude_deg"] % 360)
        assert dynamic["features"]["longest_shared_minutes"] == 180
        assert dynamic["features"]["shared_modeled_visibility_fraction"] == 1
        assert dynamic["records"][0]["cell_id"] == row["cell_id"]
        assert dynamic["start_utc"] == req.start_utc.isoformat()
        assert "raw" not in dynamic and "records" not in row["static_vector"]
        assert dynamic["provenance"]["source"] == "SYNTHETIC_TEST_DOUBLE"


def test_unknown_samples_and_no_queries_for_rejected(dataset):
    e = engine(dataset, FakeCelestial(missing=True))
    result = e.analyze(request(dataset))
    assert not result["comparison"]["ranked"]
    assert result["results"][0]["dynamic_vector"]["features"][
        "unknown_data_fraction"
    ] == pytest.approx(1 / 3)
    e = engine(dataset)
    req = request(dataset).model_copy(update={"filters": Filters(maximum_slope_deg=1)})
    result = e.analyze(req)
    assert e.celestial.requests == []
    assert all(row["dynamic_vector"] is None for row in result["results"])


def test_horizon_partial_never_clear():
    horizon = dict(
        model="TERRAIN_PARTIAL",
        far_field_complete=False,
        observer_reference_compatible=True,
        azimuth_samples=[
            dict(
                azimuth_deg=10,
                terrain_horizon_elevation_deg=5,
                verified_obstruction_lower_bound_deg=5,
            )
        ],
    )
    assert visibility(10, 4, horizon)["state"] == "TERRAIN_OBSTRUCTED"
    assert visibility(10, 6, horizon)["modeled_visible"] is None
    assert visibility(11, 4, horizon)["modeled_visible"] is None
    assert visibility(None, None, horizon)["state"] == "UNKNOWN"


def test_terrain_missing_not_ranked(dataset):
    e = engine(dataset)
    e.skyline = lambda *args: dict(
        model="TERRAIN_PARTIAL", azimuth_samples=[], far_field_complete=False
    )
    result = e.analyze(request(dataset, horizon_model="TERRAIN_PARTIAL", terrain_site_id="R04"))
    assert result["comparison"]["ranked"] == []
    assert result["results"][0]["dynamic_vector"]["features"]["unknown_data_fraction"] == 1


@pytest.mark.parametrize(
    "kind,outcome",
    [
        ("keep", "KEEP"),
        ("switch", "SWITCH"),
        ("none", "NO QUALIFYING MODELED OPTION"),
        ("missing", "INSUFFICIENT DATA"),
    ],
)
def test_delay(dataset, kind, outcome):
    def elevations(req):
        if kind == "none":
            return -5
        if kind == "switch" and req.longitude_east_deg == 315:
            return -5
        return 5

    e = engine(dataset, FakeCelestial(elevations, missing=kind == "missing"))
    result = e.delay(request(dataset), dataset.cells[0].cell_id)
    assert result["outcome"] == outcome
    requests = e.celestial.requests
    for original, delayed in zip(requests[:3], requests[3:]):
        assert (delayed.start_utc - original.start_utc).days == 7
        assert delayed.end_utc - delayed.start_utc == original.end_utc - original.start_utc
        assert original.altitude_km == delayed.altitude_km


def test_invalid_frame_no_queries(dataset):
    dataset.metadata.coordinate_frame = "UNKNOWN"
    e = engine(dataset)
    with pytest.raises(ValueError):
        e.analyze(request(dataset))
    assert not e.celestial.requests


def test_api_end_to_end_synthetic_site04(dataset, monkeypatch):
    e = engine(dataset)
    e.registry.errors = []
    monkeypatch.setattr(api, "engine", lambda: e)
    client = TestClient(app)
    assert client.get("/api/v1/science/datasets").json()["datasets"][0]["synthetic"]
    assert client.get("/api/v1/science/datasets?limit=1001").status_code == 422
    result = client.post("/api/v1/science/analysis", json=request(dataset).model_dump(mode="json"))
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["results"][0]["static_vector"]["raw"][0] == 1000
    assert client.get("/api/v1/science/scenarios/" + body["scenario_id"]).status_code == 200
    assert client.get("/api/v1/science/datasets/absent/cells").status_code == 404
    assert (
        client.post(
            "/api/v1/science/delay",
            json=request(dataset).model_dump(mode="json")
            | {"original_cell_id": dataset.cells[0].cell_id},
        ).json()["outcome"]
        == "KEEP"
    )


def test_real_v3_external_assets():
    root = os.getenv("WISPR_REAL_V3_DIR")
    if not root:
        pytest.skip(
            "MISSING DEPENDENCY: Narinder real V3 assets; synthetic tests are not real-data validation"
        )
    registry = Registry(root)
    assert not registry.errors
    assert registry.datasets
    assert any(
        not d.metadata.synthetic and d.metadata.processing_version == "3.0.0"
        for d in registry.datasets.values()
    )


@pytest.mark.live
def test_real_site04_combined():
    root = os.getenv("WISPR_REAL_V3_DIR")
    if not root or os.getenv("WISPR_LIVE_TEST") != "1":
        pytest.skip("Requires real V3 assets and WISPR_LIVE_TEST=1; no synthetic substitute")
    registry = Registry(root)
    d = next(
        d
        for d in registry.datasets.values()
        if not d.metadata.synthetic and d.metadata.region == "Site04"
    )
    ids = d.select(Filters(limit=1, qualities=["source_lola_count_and_uncertainty_not_supplied"]))[
        0
    ]["cell_ids"]
    assert ids
    req = Scenario.model_validate(
        request(d).model_dump()
        | {
            "cell_ids": ids,
            "filters": Filters(qualities=["source_lola_count_and_uncertainty_not_supplied"]),
        }
    )
    result = AnalysisEngine(registry).analyze(req)
    assert result["results"][0]["dynamic_vector"]["provenance"]["source"] == "NASA JPL Horizons"


def test_real_site04_recorded_nasa_end_to_end(monkeypatch):
    """Real V3 measurements + authentic recorded NASA; no live-network claim."""
    from pathlib import Path

    from celestial_engine.celestial_service import CelestialService
    from celestial_engine.horizons_client import HorizonsClient

    root = Path(__file__).parents[2]
    d = Dataset.read(root / "docs/evidence/unified/real_v3_two_cells.json")
    client = HorizonsClient(Path(__file__).parent / "fixtures/unified_nasa", offline=True)
    e = engine(d, CelestialService(client))
    e.registry.errors = []
    monkeypatch.setattr(api, "engine", lambda: e)
    req = Scenario(
        dataset_id=d.metadata.dataset_id,
        cell_ids=[c.cell_id for c in d.cells],
        start_utc="2026-11-15T00:00:00Z",
        end_utc="2026-11-22T00:00:00Z",
        step_minutes=60,
        minimum_shared_minutes=60,
        filters=Filters(qualities=["source_lola_count_and_uncertainty_not_supplied"]),
    )
    with TestClient(app) as web:
        response = web.post("/api/v1/science/analysis", json=req.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    row = response.json()["results"][0]
    assert row["cell_id"] == "SITE04_R000_C000"
    assert row["cell"]["latitude_deg"] == -89.7787655990766
    assert row["cell"]["longitude_deg"] == -167.51751061504552
    assert row["static_vector"]["raw"] == [
        1072.0976434326171,
        32.13135594956228,
        0.9163221785602584,
    ]
    assert row["dynamic_vector"]["features"]["unknown_data_fraction"] == 0
    assert row["dynamic_vector"]["observer"]["altitude_km"] == 0
    assert all(
        q["delivery"] == "VERIFIED_CACHE"
        for q in row["dynamic_vector"]["provenance"]["queries"].values()
    )
    delayed = e.delay(req, d.cells[0].cell_id)
    assert delayed["outcome"] == "KEEP"
    assert len(delayed["delayed"]["comparison"]["ranked"]) == 2


def test_duplicate_utc_and_wrong_position_rejected(dataset):
    class Broken(FakeCelestial):
        def ephemeris(self, req):
            result = super().ephemeris(req)
            result.records.append(result.records[0])
            return result

    with pytest.raises(ValueError, match="duplicate UTC"):
        engine(dataset, Broken()).analyze(request(dataset))

    class WrongPosition(FakeCelestial):
        def ephemeris(self, req):
            result = super().ephemeris(req)
            result.records[0].latitude_deg = 0
            return result

    with pytest.raises(ValueError, match="position"):
        engine(dataset, WrongPosition()).analyze(request(dataset))


def test_sun_available_when_earth_missing(dataset):
    class Partial(FakeCelestial):
        def ephemeris(self, req):
            result = super().ephemeris(req)
            for row in result.records:
                row.earth_elevation_deg = None
                row.earth_azimuth_deg = None
                row.valid = False
            return result

    features = engine(dataset, Partial()).analyze(request(dataset))["results"][0]["dynamic_vector"][
        "features"
    ]
    assert features["sun_modeled_visibility_fraction"] == 1
    assert features["earth_modeled_visibility_fraction"] is None
    assert features["unknown_data_fraction"] == 1


def test_actual_horizon_position_and_reference_gate(dataset, monkeypatch):
    from app.integration.engine import horizon_at

    seen = {}

    def fake_horizon(site, height, step, *, position):
        seen["position"] = position
        return dict(
            observer_ground_height_m=1000,
            source_manifest={"vertical_reference": "unverified"},
            azimuth_samples=[{"azimuth_deg": 10, "terrain_horizon_elevation_deg": 30}],
        )

    monkeypatch.setattr("app.integration.engine.terrain.horizon", fake_horizon)
    req = request(dataset, horizon_model="TERRAIN_PARTIAL", terrain_site_id="R04")
    horizon = horizon_at(dataset, dataset.cells[0], req)
    assert seen["position"] == (-89, 315)
    assert visibility(10, 4, horizon)["state"] == "UNKNOWN_OBSERVER_REFERENCE"


def test_missing_static_evidence_delay_is_insufficient(dataset):
    for cell in dataset.cells:
        cell.quality = "UNKNOWN"
    assert (
        engine(dataset).delay(request(dataset), dataset.cells[0].cell_id)["outcome"]
        == "INSUFFICIENT DATA"
    )


@pytest.mark.parametrize(
    "uncertainty",
    [{"sigma_m": None}, {"sigma_m": float("nan")}, {"sigma_m": True}, {"kind": "descriptive"}],
)
def test_null_or_untyped_uncertainty_never_qualifies(dataset, uncertainty):
    dataset.cells[0].uncertainty = uncertainty
    with pytest.raises(ValueError, match="uncertainty"):
        dataset.similarity(dataset.cells[0].cell_id)
