import math

import numpy as np
import pytest
from astropy import units as u

from lunar_global.grid import RADIUS_M, batches, cell_id, describe, hpx, lookup, parse_id


@pytest.mark.parametrize("nside", [64, 128, 256])
def test_complete_hierarchy_and_area(nside):
    seen = 0
    for batch in batches(nside):
        pixels = batch["pixel"]
        actual = hpx(nside).lonlat_to_healpix(
            batch["longitude_deg"] * u.deg, batch["latitude_deg"] * u.deg
        )
        np.testing.assert_array_equal(actual, pixels)
        parent = hpx(nside // 2).lonlat_to_healpix(
            batch["longitude_deg"] * u.deg, batch["latitude_deg"] * u.deg
        )
        np.testing.assert_array_equal(parent, pixels // 4)
        assert pixels[0] == seen
        seen += len(pixels)
    assert seen == 12 * nside**2
    assert math.isclose(describe(cell_id(nside, 0))["area_m2"] * seen, 4 * math.pi * RADIUS_M**2)


def test_poles_wrap_neighbors_and_ids():
    for lat in [-90, -89.999, 0, 89.999, 90]:
        assert lookup(lat, -1) == lookup(lat, 359)
        assert lookup(lat, 0) == lookup(lat, 360)
    for p in [0, 12345, 196607]:
        value = cell_id(128, p)
        info = describe(value)
        assert info["boundary_lonlat"][0] == info["boundary_lonlat"][-1]
        for neighbor in info["neighbors"]:
            assert value in describe(neighbor)["neighbors"]
        assert parse_id(value) == (128, p)
    for value in ["MOON:HPX:NESTED:128:196608", "MOON:HPX:NESTED:127:0", "MOON:HPX:NESTED:128:01"]:
        with pytest.raises(ValueError):
            parse_id(value)
    with pytest.raises(ValueError):
        lookup(float("nan"), 0)
