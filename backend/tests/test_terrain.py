import math
import pytest
from app.providers.terrain import curvature_angle,terrain_metadata


def test_spherical_flat_ground_drops_below_horizon():
    assert curvature_angle(1000,0)<0
    assert curvature_angle(1000,0)==pytest.approx(-math.degrees(1000/(2*1737400)),rel=1e-6)


def test_synthetic_ridge_obstructs_and_observer_height_matters():
    assert curvature_angle(1000,100)>5
    assert curvature_angle(1000,100-10)<curvature_angle(1000,100)


def test_missing_dem_is_explicit(monkeypatch):
    monkeypatch.delenv('DEM_R01',raising=False)
    r=terrain_metadata('R01')
    assert r['coverage']=='UNAVAILABLE'
    assert not r['far_field_complete']
