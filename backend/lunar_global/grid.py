"""HEALPix NESTED on a lunar sphere, never an Earth coordinate system.

Cell edges are analytic HEALPix curves. Returned rings sample those curves and
declare sampling explicitly; they are not exact geodesic polygon edges.
"""

import math
from functools import lru_cache

import numpy as np
from astropy import units as u
from astropy_healpix import HEALPix

RADIUS_M = 1737400.0
FRAME = "MOON_ME_DE421"
GRID_VERSION = "moon-hpx-nested-v1"
LEVELS = (64, 128, 256, 512)


@lru_cache(maxsize=10)
def hpx(nside):
    if type(nside) is not int or nside < 1 or nside > 512 or nside & (nside - 1):
        raise ValueError("NSIDE must be a power of two from 1 through 512")
    return HEALPix(nside=nside, order="nested")


def cell_id(nside, pixel):
    if type(pixel) is not int or not 0 <= pixel < hpx(nside).npix:
        raise ValueError("Pixel outside grid")
    return f"MOON:HPX:NESTED:{nside}:{pixel}"


def parse_id(value):
    try:
        prefix, kind, order, nside, pixel = value.split(":")
        nside, pixel = int(nside), int(pixel)
        if (prefix, kind, order) != ("MOON", "HPX", "NESTED"):
            raise ValueError()
        if cell_id(nside, pixel) != value:
            raise ValueError()
        return nside, pixel
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid canonical lunar cell ID") from exc


def lookup(latitude, longitude, nside=128):
    if not (math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90):
        raise ValueError("Finite longitude and latitude in [-90,90] required")
    return cell_id(
        nside, int(hpx(nside).lonlat_to_healpix((longitude % 360) * u.deg, latitude * u.deg))
    )


def boundary(nside, pixel, step=16):
    cell_id(nside, pixel)
    if not 1 <= step <= 4096:
        raise ValueError("Boundary step outside budget")
    lon, lat = hpx(nside).boundaries_lonlat([pixel], step=step)
    points = np.column_stack((lon.to_value(u.deg)[0], lat.to_value(u.deg)[0])).tolist()
    return points + [points[0]]


def describe(value, step=16):
    nside, pixel = parse_id(value)
    hp = hpx(nside)
    lon, lat = hp.healpix_to_lonlat(pixel)
    with np.errstate(invalid="ignore"):
        adjacent = hp.neighbours(pixel)
    return dict(
        cell_id=value,
        nside=nside,
        pixel=pixel,
        level=int(math.log2(nside)),
        latitude_deg=float(lat.to_value(u.deg)),
        longitude_deg=float(lon.to_value(u.deg)),
        parent_id=cell_id(nside // 2, pixel // 4) if nside > 1 else None,
        children=[cell_id(nside * 2, pixel * 4 + i) for i in range(4)] if nside < 512 else [],
        neighbors=[cell_id(nside, int(i)) for i in adjacent if i >= 0],
        area_m2=4 * math.pi * RADIUS_M**2 / hp.npix,
        boundary_lonlat=boundary(nside, pixel, step),
        boundary_step=step,
        boundary_method="Samples of analytic HEALPix edges; not WGS84 GeoJSON",
        coordinate_frame=FRAME,
        reference_radius_m=RADIUS_M,
        latitude_type="planetocentric_spherical",
        longitude_convention="east_positive_0_360",
        grid_version=GRID_VERSION,
    )


def batches(nside, size=4096):
    if not 1 <= size <= 16384:
        raise ValueError("Batch size outside budget")
    hp = hpx(nside)
    for start in range(0, hp.npix, size):
        pixels = np.arange(start, min(start + size, hp.npix), dtype=np.int64)
        lon, lat = hp.healpix_to_lonlat(pixels)
        yield dict(
            pixel=pixels, longitude_deg=lon.to_value(u.deg), latitude_deg=lat.to_value(u.deg)
        )
