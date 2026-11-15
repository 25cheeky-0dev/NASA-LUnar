"""Analytical oracles and actual raster failures, independent of production maxima."""

import copy
import json
import math
import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import CRS, Transformer
from rasterio.transform import from_origin

from app.providers.horizon_comparison import compare_ephemeris
from app.providers.horizon_geometry import elevation_angle
from app.providers.terrain import TerrainUnavailable, compute_horizon, horizon
from app.providers.terrain_horizon import (
    ReferenceSettings,
    TerrainHorizonEngine,
    classify_visibility,
    file_sha256,
)

R = 1737400.0
CRS_MOON = CRS.from_proj4(f"+proj=stere +lat_0=-90 +lon_0=0 +R={R} +units=m")


@pytest.fixture
def make_engine(tmp_path):
    count = 0

    def make(*, ridge=False, hole=False, center_y=-7500, references=None, step=None):
        nonlocal count
        count += 1
        path = tmp_path / f"dem{count}.tif"
        transform = from_origin(-502.5, center_y + 502.5, 5, 5)
        xs = np.arange(201) * 5 - 500
        ys = center_y + 500 - np.arange(201) * 5
        xx, yy = np.meshgrid(xs, ys)
        z = np.full((201, 201), 1000.0, dtype="float64")
        if ridge:
            z[(xx >= -110) & (xx <= -90) & (abs(yy - center_y) <= 60)] += 40
        if hole:
            z[:, 90] = np.nan  # Entire strip at x=-50, before the ridge.
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=201,
            height=201,
            count=1,
            dtype="float64",
            crs=CRS_MOON,
            transform=transform,
            nodata=np.nan,
        ) as dst:
            dst.write(z, 1)
        lon, lat = Transformer.from_crs(CRS_MOON, CRS_MOON.geodetic_crs, always_xy=True).transform(
            0, center_y
        )
        cells = {
            "original-id": dict(latitude_deg=lat, longitude_east_deg=lon, x_m=0.0, y_m=center_y)
        }
        return TerrainHorizonEngine(
            path, cells, file_sha256(path), references=references, sample_step_m=step
        )

    return make


def test_exact_geometry_against_independent_moon_centered_vectors():
    for ground in (-5000, 0, 2000):
        for height in (0, 1, 50):
            for d in (5, 100, 1000, 16000):
                for z in (-3000, 0, 3500):
                    angle = d / R
                    observer = np.array([R + ground + height, 0, 0])
                    target = (R + z) * np.array([math.cos(angle), math.sin(angle), 0])
                    sight = target - observer
                    expected = math.degrees(math.atan2(sight[0], np.linalg.norm(sight[1:])))
                    assert elevation_angle(d, observer[0], R + z, R) == pytest.approx(
                        expected, abs=3e-9
                    )


def test_flat_sphere_analytic_horizon_and_elevated_observer():
    d = np.array([1, 5, 100, 1000, 16000.0])
    assert elevation_angle(d, R + 1000, R + 1000, R) == pytest.approx(-np.degrees(d / (2 * R)))
    for h in (1, 10, 100):
        theta = math.acos(R / (R + h))
        assert elevation_angle(R * theta, R + h, R, R) == pytest.approx(
            -math.degrees(theta), abs=1e-10
        )


def test_flat_raster_and_boundary(make_engine):
    engine = make_engine()
    result = engine.compute_horizon("original-id", 0, [0, 90, 180, 270])
    assert result["observer_ground_height_m"] == 1000
    for ray in result["azimuth_samples"]:
        assert ray["terrain_horizon_elevation_deg"] == pytest.approx(
            -math.degrees(2.5 / (2 * R)), abs=1e-10
        )
        assert ray["stop_reason"] == "SOURCE_BOUNDARY"
        assert 490 < ray["supported_radius_m"] < 510
        assert not ray["far_field_complete"]
        assert classify_visibility(ray, 80, reference_compatible=True) == "UNKNOWN"


def test_single_direction_ridge_and_observer_height(make_engine):
    engine = make_engine(ridge=True)
    low = engine.compute_horizon("original-id", 1, [90, 270])
    high = engine.compute_horizon("original-id", 10, [90])
    east, west = low["azimuth_samples"]
    assert east["terrain_horizon_elevation_deg"] > 20
    assert west["terrain_horizon_elevation_deg"] < 0
    assert (
        high["azimuth_samples"][0]["terrain_horizon_elevation_deg"]
        < east["terrain_horizon_elevation_deg"]
    )
    assert 85 < east["obstruction_distance_m"] < 115
    p = east["obstruction"]
    theta = p["distance_m"] / R
    expected = math.degrees(
        math.atan2(
            (R + p["source_elevation_m"]) * math.cos(theta) - (R + 1001),
            (R + p["source_elevation_m"]) * math.sin(theta),
        )
    )
    assert east["terrain_horizon_elevation_deg"] == pytest.approx(expected, abs=1e-8)


def test_missing_pixels_end_prefix_before_ridge(make_engine):
    engine = make_engine(ridge=True, hole=True)
    ray = engine.compute_horizon("original-id", 1, [90])["azimuth_samples"][0]
    assert ray["stop_reason"] == "NODATA"
    assert 40 <= ray["supported_radius_m"] < 50
    assert ray["terrain_horizon_elevation_deg"] < 0
    assert ray["first_unknown_distance_m"] == ray["supported_radius_m"] + 2.5


def test_wraparound_all_azimuths_and_cache_isolation(make_engine):
    engine = make_engine(ridge=True)
    a = engine.compute_horizon("original-id", 1, [-270, 90, 450, 0, 360])
    assert a["azimuth_samples"][0] == a["azimuth_samples"][1] == a["azimuth_samples"][2]
    a["azimuth_samples"][0]["terrain_horizon_elevation_deg"] = 900
    b = engine.compute_horizon("original-id", 1, [-270, 90, 450, 0, 360])
    assert b["azimuth_samples"][0]["terrain_horizon_elevation_deg"] < 90
    skyline = engine.diagnostic_skyline("original-id")
    assert [r["azimuth_deg"] for r in skyline["azimuth_samples"]] == list(range(360))
    assert skyline["angular_resolution_deg"] == 1
    json.dumps(skyline, allow_nan=False)


def test_polar_near_pole_rays_and_exact_pole_rejection(make_engine):
    engine = make_engine(center_y=-0.05)
    result = engine.compute_horizon("original-id", 1, [0, 90, 180, 270])
    assert all(math.isfinite(r["terrain_horizon_elevation_deg"]) for r in result["azimuth_samples"])
    engine.cells["original-id"]["latitude_deg"] = -90
    with pytest.raises(TerrainUnavailable, match="pole"):
        engine.compute_horizon("original-id", 1, [0])


@pytest.mark.parametrize("lat,lon", [(math.nan, 0), (-91, 0), (0, 0)])
def test_invalid_observer(make_engine, lat, lon):
    engine = make_engine()
    engine.cells["original-id"] = dict(latitude_deg=lat, longitude_east_deg=lon)
    with pytest.raises(TerrainUnavailable):
        engine.compute_horizon("original-id", 1, [0])


def test_invalid_observer_nodata_and_mismatched_centers(make_engine):
    engine = make_engine(hole=True)
    cell = engine.cells["original-id"]
    cell["x_m"] = 20
    with pytest.raises(TerrainUnavailable, match="centers disagree"):
        engine.compute_horizon("original-id", 1, [0])
    lon, lat = engine.reverse.transform(-50, -7500)
    engine.cells["original-id"] = dict(latitude_deg=lat, longitude_east_deg=lon)
    with pytest.raises(TerrainUnavailable, match="NODATA"):
        engine.compute_horizon("original-id", 1, [0])


@pytest.mark.parametrize("az,height", [([math.nan], 1), ([0], -1), ([0], math.inf), ([], 1)])
def test_invalid_request(make_engine, az, height):
    with pytest.raises(ValueError):
        make_engine().compute_horizon("original-id", height, az)


def test_checksum_and_unknown_original_id(make_engine):
    engine = make_engine()
    with pytest.raises(TerrainUnavailable, match="SHA-256"):
        TerrainHorizonEngine(engine.source_path, engine.cells, "0" * 64)
    with pytest.raises(TerrainUnavailable, match="original cell ID"):
        engine.compute_horizon("invented-id", 1, [0])


def test_verified_local_block_does_not_require_far_field(make_engine):
    refs = ReferenceSettings(
        vertical_reference_verified=True,
        vertical_reference_evidence="Analytical synthetic sphere, constructed radii",
        elevation_error_bound_m=0,
        error_bound_evidence="Exact synthetic surface",
    )
    engine = make_engine(ridge=True, references=refs)
    ray = engine.compute_horizon("original-id", 1, [90])["azimuth_samples"][0]
    assert classify_visibility(ray, 10, reference_compatible=True) == "TERRAIN_BLOCKED"
    assert classify_visibility(ray, 30, reference_compatible=True) == "UNKNOWN"
    assert classify_visibility(ray, 10, reference_compatible=False) == "UNKNOWN"
    uncertain = make_engine(ridge=True).compute_horizon("original-id", 1, [90])["azimuth_samples"][
        0
    ]
    assert classify_visibility(uncertain, 10, reference_compatible=True) == "UNKNOWN"


def test_visibility_requires_all_clearance_gates():
    ray = dict(
        near_field_complete=True,
        far_field_complete=True,
        resolution_verified=True,
        verified_horizon_upper_bound_deg=2,
    )
    assert classify_visibility(ray, 3, reference_compatible=True) == "TERRAIN_VISIBLE"
    for flag in ("near_field_complete", "far_field_complete", "resolution_verified"):
        incomplete = dict(ray, **{flag: False})
        assert classify_visibility(incomplete, 3, reference_compatible=True) == "UNKNOWN"


def test_incompatible_vertical_reference_and_hard_bound(make_engine):
    with pytest.raises(ValueError, match="independent evidence"):
        ReferenceSettings(vertical_reference_verified=True)
    with pytest.raises(ValueError, match="height conversion"):
        ReferenceSettings(height_interpretation="horizons_lunar_reference")
    with pytest.raises(ValueError, match="hard error bound"):
        ReferenceSettings(elevation_error_bound_m=0.3)
    engine = make_engine()
    a = engine.compute_horizon("original-id", 1, [90])
    engine.references = replace(engine.references, height_offset_m=1000)
    b = engine.compute_horizon("original-id", 1, [90])
    assert a["observer_radius_m"] + 1000 == b["observer_radius_m"]
    assert len(engine._cache) == 2


def test_original_provider_contract_uses_new_core(make_engine, monkeypatch):
    engine = make_engine(ridge=True)
    manifest = dict(
        z_units="metre",
        source_url="https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/test",
        frame="MOON_ME_DE421",
        vertical_reference="unverified",
        raw_sha256=engine.digest,
    )
    engine.source_path.with_suffix(".tif.json").write_text(json.dumps(manifest))
    monkeypatch.setenv("DEM_R01", str(engine.source_path))
    c = engine.cells["original-id"]
    r = horizon(
        "R01", 1, 5, position=(c["latitude_deg"], c["longitude_east_deg"]), azimuths_deg=[90]
    )
    expected = compute_horizon("original-id", 1, [90], engine=engine)
    assert r["azimuth_samples"] == expected["azimuth_samples"]
    assert r["model"] == "TERRAIN_PARTIAL"


def test_exact_directions_preserve_source_and_reject_missing_reference(make_engine):
    engine = make_engine(ridge=True)
    c = engine.cells["original-id"]
    row = dict(
        timestamp_utc="2026-11-15T00:00:00Z",
        sun_azimuth_deg=91.234567,
        sun_elevation_deg=3.141592,
        earth_azimuth_deg=359.987654,
        earth_elevation_deg=-2.123456,
        latitude_deg=c["latitude_deg"],
        longitude_east_deg=c["longitude_east_deg"],
        altitude_km=0,
        source="NASA_JPL_HORIZONS",
        valid=True,
        quality="SOURCE_BACKED",
    )
    source = dict(records=[row], metadata={})
    before = copy.deepcopy(source)
    joined = compare_ephemeris(engine, "original-id", 1, source)
    assert source == before
    assert joined["records"][0]["source_observation"] == row
    for body in ("sun", "earth"):
        result = joined["records"][0]["terrain"][body]
        assert result["state"] == "UNKNOWN"
        assert result["ray"]["azimuth_deg"] == row[f"{body}_azimuth_deg"]
    assert joined["original_metadata"] == before["metadata"]


def test_legacy_integration_does_not_trust_a_relabelled_datum(monkeypatch):
    from types import SimpleNamespace

    from app.integration.engine import horizon_at

    monkeypatch.setattr(
        "app.integration.engine.terrain.horizon",
        lambda *a, **k: dict(
            source_manifest={"vertical_reference": "horizons_lunar_reference"},
            observer_ground_height_m=-1,
            observer_height_m=1,
        ),
    )
    dataset = SimpleNamespace(east_longitude=lambda cell: 20, metadata=SimpleNamespace(source={}))
    cell = SimpleNamespace(latitude_deg=-89)
    request = SimpleNamespace(
        horizon_model="TERRAIN_PARTIAL", terrain_site_id="R04", observer_height_m=1, altitude_km=0
    )
    assert horizon_at(dataset, cell, request)["observer_reference_compatible"] is False


@pytest.mark.parametrize("step", [0, -1, math.nan, math.inf, 5])
def test_invalid_sampling_resolution(make_engine, step):
    with pytest.raises(ValueError):
        make_engine(step=step)


@pytest.mark.skipif(
    not os.getenv("WISPR_REAL_V3_DIR"), reason="Set WISPR_REAL_V3_DIR to frozen package"
)
def test_real_nasa_join_and_reference_failures():
    from celestial_engine.celestial_service import CelestialService
    from celestial_engine.horizons_client import HorizonsClient, parameters
    from celestial_engine.schemas import EphemerisRequest

    engine = TerrainHorizonEngine.from_v3(os.environ["WISPR_REAL_V3_DIR"])
    cell_id = "SITE04_R000_C000"
    c = engine.cells[cell_id]
    req = EphemerisRequest(
        latitude_deg=c["latitude_deg"],
        longitude_east_deg=c["longitude_east_deg"],
        altitude_km=0,
        start_utc="2026-11-15T00:00:00Z",
        end_utc="2026-11-22T00:00:00Z",
        step_minutes=60,
    )
    client = HorizonsClient(Path(__file__).parent / "fixtures/unified_nasa", offline=True)
    ephem = CelestialService(client).ephemeris(req).model_dump(mode="json")
    ephem["records"] = ephem["records"][:2]
    original = copy.deepcopy(ephem)
    raw = {b: client.cache.get(parameters(t, req))[0] for b, t in (("sun", 10), ("earth", 399))}
    joined = compare_ephemeris(engine, cell_id, 1, ephem, raw_sources=raw)
    assert [r["source_observation"] for r in joined["records"]] == original["records"]
    assert ephem == original
    assert set(joined["compatibility_failures"]) == {
        "DEM_VERTICAL_REFERENCE_UNVERIFIED",
        "OBSERVER_POSITION_OR_ALTITUDE_MISMATCH",
    }
    for row in joined["records"]:
        for body in ("sun", "earth"):
            assert row["terrain"][body]["state"] == "UNKNOWN"
            assert (
                row["terrain"][body]["ray"]["azimuth_deg"]
                == row["source_observation"][f"{body}_azimuth_deg"]
            )
    damaged = dict(raw, sun=b"corrupted")
    bad = compare_ephemeris(engine, cell_id, 1, ephem, raw_sources=damaged)
    assert any("checksum mismatch" in r for r in bad["compatibility_failures"])
    ephem["records"][0]["sun_elevation_deg"] += 1
    bad = compare_ephemeris(engine, cell_id, 1, ephem, raw_sources=raw)
    assert "ROW_DIFFERS_FROM_NASA_SOURCE" in bad["records"][0]["terrain"]["sun"]["reasons"]


@pytest.mark.skipif(
    not os.getenv("WISPR_REAL_V3_DIR"), reason="Set WISPR_REAL_V3_DIR to frozen package"
)
def test_real_site04_full_source_and_original_cells():
    engine = TerrainHorizonEngine.from_v3(os.environ["WISPR_REAL_V3_DIR"])
    assert engine.digest == "38ff70dbdf2f066c2cfa94a646c3a59d653ce7f6b4528b15fc1b43ee397ce758"
    assert (engine.width, engine.height) == (3200, 3200)
    for cell_id in ("SITE04_R000_C000", "SITE04_R019_C019"):
        result = engine.compute_horizon(cell_id, 1, [0, 45.123456, 90, 180, 270, 359.9])
        assert not result["vertical_reference_verified"]
        assert not result["far_field_complete"]
        assert len(engine._cache) <= 2  # Never precompute the other 398 cells.
        for ray in result["azimuth_samples"]:
            assert ray["supported_radius_m"] > 2000
            assert ray["stop_reason"] == "SOURCE_BOUNDARY"
            assert classify_visibility(ray, -5, reference_compatible=False) == "UNKNOWN"
            p = ray["obstruction"]
            value, _ = engine._sample([p["source_x_m"]], [p["source_y_m"]])
            assert p["source_elevation_m"] == pytest.approx(value[0])
        json.dumps(result, allow_nan=False)
