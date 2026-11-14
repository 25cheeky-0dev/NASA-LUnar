"""Independent scalar references and adversarial snapshot checks."""

import json
import math
import os
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pyproj import Geod

from app.main import app
from lunar_global.api import Candidates, Similarity
from lunar_global.features import FEATURES, aggregate_pixels, fit_zscore, native_terrain
from lunar_global.grid import RADIUS_M, boundary, describe
from lunar_global.service import GlobalStore
from lunar_global.sources import SourceProduct
from lunar_global.storage import build_grid, verified_files, write_json

ROOT = Path("data/lunar-v1")


def test_serialization_failure_does_not_create_manifest(tmp_path):
    with pytest.raises(TypeError):
        write_json(tmp_path / "manifest.json", {"count": np.int64(1)})
    assert not (tmp_path / "manifest.json").exists()


def test_snapshot_corruption_and_immutability(tmp_path):
    build_grid(tmp_path, 1)
    directory = tmp_path / "global_grid/nside=1"
    paths, manifest = verified_files(directory)
    assert manifest["count"] == 12
    with pytest.raises(ValueError):
        build_grid(tmp_path, 1)
    paths[0].write_bytes(b"corrupt parquet")
    with pytest.raises(ValueError, match="checksum"):
        verified_files(directory)


def test_spherical_boundary_area_independent_geod():
    geod = Geod(a=RADIUS_M, b=RADIUS_M)
    for p in (0, 100, 12345, 163840, 196607):
        coords = np.asarray(boundary(128, p, 128))
        area, _ = geod.polygon_area_perimeter(coords[:, 0], coords[:, 1])
        expected = describe(f"MOON:HPX:NESTED:128:{p}")["area_m2"]
        assert abs(abs(area) / expected - 1) < 1e-5


def test_zscore_population_and_missing():
    rows = [
        dict(cell_id=str(i), elevation_m=i * 10, slope_deg=i, roughness_m=i * 3) for i in range(3)
    ]
    fit = fit_zscore(rows, "test-synthetic")
    assert fit["means"] == [10, 1, 3]
    assert fit_zscore(list(reversed(rows)), "test-synthetic") == fit
    rows[0]["slope_deg"] = None
    with pytest.raises(ValueError):
        fit_zscore(rows, "test-synthetic")


def test_api_bounds_and_contracts():
    with TestClient(app) as client:
        for url in (
            "cells/lookup?latitude=91&longitude=0",
            "cells/lookup?latitude=0&longitude=nan",
            "cells/lookup?latitude=0&longitude=0&nside=127",
            "cells?limit=1001",
            "cells/MOON:HPX:NESTED:128:999999",
        ):
            assert client.get("/api/v1/science/global/" + url).status_code == 422
        assert (
            client.post(
                "/api/v1/science/global/candidates", json={"bbox": [0, 20, 10, -20]}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/science/global/similarity",
                json={"reference_cell_id": "x", "normalization_version": "unknown"},
            ).status_code
            == 422
        )
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/v1/science/global/") or "/layer-images/" in path:
            continue
        for operation in operations.values():
            assert "$ref" in operation["responses"]["200"]["content"]["application/json"]["schema"]


@pytest.fixture
def actual():
    if not os.getenv("WISPR_GLOBAL_REAL"):
        pytest.skip("Opt-in real downloaded global products required")
    source = SourceProduct.model_validate_json(
        (ROOT / "source_products/lola/source.json").read_text()
    )
    return source, native_terrain(ROOT / "source_products/lola/ldem_4.img", source)


def test_real_native_scalar_reference(actual):
    source, (z, slopes, roughness) = actual
    raw = np.memmap(
        ROOT / "source_products/lola/ldem_4.img", dtype="<i2", mode="r", shape=(720, 1440)
    )
    for row, col in [(1, 1), (100, 400), (359, 1439), (600, 800), (718, 600)]:
        assert z[row, col] == int(raw[row, col]) * 0.5
        north = (
            (float(raw[row - 1, col]) - float(raw[row + 1, col]))
            * 0.5
            / (2 * RADIUS_M * math.pi / 720)
        )
        east = (
            (float(raw[row, (col + 1) % 1440]) - float(raw[row, (col - 1) % 1440]))
            * 0.5
            / (2 * RADIUS_M * math.pi / 720 * math.cos(math.radians(90 - (row + 0.5) / 4)))
        )
        assert slopes[row, col] == pytest.approx(
            math.degrees(math.atan(math.sqrt(north * north + east * east)))
        )
        window = [
            float(raw[r, c % 1440]) * 0.5
            for r in range(row - 1, row + 2)
            for c in range(col - 1, col + 2)
        ]
        mean = sum(window) / 9
        assert roughness[row, col] == pytest.approx(
            math.sqrt(sum((v - mean) ** 2 for v in window) / 9), abs=1e-7
        )
    assert np.isnan(slopes[0]).all() and np.isnan(roughness[-1]).all()
    with pytest.raises(ValueError):
        source.model_copy(update={"coordinate_frame": "MOON_PA"}).validate_alignment()
    with pytest.raises(ValueError):
        source.model_copy(update={"reference_radius_m": 6371000}).validate_alignment()


def test_real_quadrature_and_similarity(actual):
    _, native = actual
    pixels = np.array([0, 1, 100, 12345, 50000, 100000, 163840, 196607])
    low = aggregate_pixels(pixels, 128, native, 16)
    high = aggregate_pixels(pixels, 128, native, 32)
    # Explicit numerical discretization acceptance, not physical uncertainty.
    for key, tolerance in zip(FEATURES, [10, 0.5, 5]):
        assert np.max(np.abs(low[key] - high[key])) < tolerance
    store = GlobalStore(ROOT)
    reference = "MOON:HPX:NESTED:128:12345"
    with pytest.raises(ValueError, match="uncertainty"):
        store.similarity(Similarity(reference_cell_id=reference))
    result = store.similarity(
        Similarity(reference_cell_id=reference, accept_unknown_uncertainty=True)
    )
    ref = store.vector(reference)["raw_values"]
    for row in result["matches"]:
        expected = math.sqrt(
            sum(((row[k] - v) / scale) ** 2 for k, v, scale in zip(FEATURES, ref, [1000, 10, 10]))
        )
        assert row["distance"] == pytest.approx(expected)
    assert store.candidates(Candidates(bbox=(350, -10, 10, 10), limit=5))[0]


def test_real_thermal_matches_original_ascii(actual):
    import csv

    from lunar_global.thermal import thermal_context

    path = ROOT / "source_products/diviner/global_cumul_avg_cyl_90s80s_002.tab"
    with path.open(newline="") as stream:
        reader = csv.reader(stream)
        next(reader)
        first = list(map(float, next(reader)))
    result = thermal_context(ROOT, first[1], first[0], 0)
    assert len(result["measurements"]) == 1
    row = result["measurements"][0]
    assert row["tbol"] == first[-1]
    assert row["local_time_hours"] == first[2]
    assert thermal_context(ROOT, 0, 0, 0)["missing_reason"] == "NO_INGESTED_THERMAL_COVERAGE"
    with pytest.raises(ValueError):
        thermal_context(ROOT, -89, 0, 96)


def test_global_analysis_reuses_scenario_store(monkeypatch):
    from types import SimpleNamespace

    from app.integration.api import scenarios
    from lunar_global import api

    # Genuine recorded result, not a fabricated NASA observation.
    path = Path(__file__).resolve().parents[3] / "docs/evidence/global/global-nasa-analysis.json"
    result = json.loads(path.read_text())
    result.pop("scenario_id", None)
    monkeypatch.setattr(
        api, "selected_engine", lambda *args: SimpleNamespace(analyze=lambda q: result)
    )
    with TestClient(app) as client:
        response = client.post("/api/v1/science/global/analysis", json=result["scenario"])
    assert response.status_code == 200
    assert response.json()["scenario_id"] in scenarios


def test_optional_spectral_missing_bands(actual):
    from lunar_global.spectral import validate_reflectance_registration

    source, _ = actual
    spectral = source.model_copy(
        update={
            "instrument": "M3",
            "product_type": "spectral",
            "units": "dimensionless reflectance",
        }
    )
    with pytest.raises(ValueError, match="bands"):
        validate_reflectance_registration(spectral, [1000, 2000], [0.1], ["GOOD"])
    out = validate_reflectance_registration(
        spectral, [1000, 2000], [0.1, None], ["GOOD", "MISSING"]
    )
    assert out["mineral_abundance"] is None and out["indices"] == {}
