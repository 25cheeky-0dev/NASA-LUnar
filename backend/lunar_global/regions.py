"""Projection-aware regional crosswalk, with numerical convergence evidence."""

import math

import numpy as np
from astropy import units as u
from pyproj import CRS, Transformer
from shapely.geometry import Polygon

from .grid import FRAME, RADIUS_M, boundary, cell_id, hpx


def crosswalk(dataset, nside=128):
    meta = dataset.metadata
    if (
        meta.coordinate_frame != FRAME
        or meta.reference_radius_m != RADIUS_M
        or meta.latitude_type != "planetocentric_spherical"
        or not meta.projected_crs
    ):
        raise ValueError("Regional frame/sphere/latitude/projection is incompatible")
    crs = CRS.from_user_input(meta.projected_crs)
    if crs.ellipsoid.semi_major_metre != RADIUS_M or crs.ellipsoid.inverse_flattening != 0:
        raise ValueError("Regional projection is not the declared lunar sphere")
    if not crs.is_projected or any(a.unit_name != "metre" for a in crs.axis_info):
        raise ValueError("Projected metre coordinates required")
    transform = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
    hp = hpx(nside)
    results = []
    for cell in dataset.cells:
        if not cell.geometry or cell.geometry["crs"] != meta.projected_crs:
            raise ValueError("Missing or inconsistent regional geometry")
        native = Polygon(cell.geometry["coordinates"][0])
        if not native.is_valid or native.area <= 0:
            raise ValueError("Invalid regional footprint")
        # Conservative bound from native geometry, with factor two projection
        # margin; restricted to the tiny, near-pole Site04 package.
        if cell.region != "Site04" or abs(cell.latitude_deg) < 85 or native.area > 1e6:
            raise ValueError("Crosswalk currently validates bounded Site04 footprints only")
        radius = (
            max(
                math.hypot(x - cell.projected_x, y - cell.projected_y)
                for x, y in native.exterior.coords
            )
            * 2
            / RADIUS_M
        )
        candidates = hp.cone_search_lonlat(
            dataset.east_longitude(cell) * u.deg, cell.latitude_deg * u.deg, radius * u.rad
        )
        previous = None
        for step in (32, 64, 128, 256, 512, 1024, 2048, 4096):
            weights = {}
            for p in candidates:
                ring = np.asarray(boundary(nside, int(p), step))
                x, y = transform.transform(ring[:, 0], ring[:, 1])
                poly = Polygon(zip(x, y))
                if not poly.is_valid:
                    raise ValueError("Invalid transformed HEALPix boundary")
                fraction = native.intersection(poly).area / native.area
                if fraction > 1e-12:
                    weights[int(p)] = fraction
            error = (
                max(
                    (
                        abs(weights.get(p, 0) - previous.get(p, 0))
                        for p in set(weights) | set(previous or {})
                    ),
                    default=0,
                )
                if previous is not None
                else 1
            )
            if previous is not None and error < 1e-6 and abs(sum(weights.values()) - 1) < 1e-6:
                break
            previous = weights
        else:
            raise ValueError("Crosswalk failed geometric convergence")
        for p, fraction in weights.items():
            results.append(
                dict(
                    dataset_id=meta.dataset_id,
                    regional_cell_id=cell.cell_id,
                    global_cell_id=cell_id(nside, p),
                    overlap_fraction=fraction,
                    method="Native projected polygon intersection with densified HEALPix curves",
                    boundary_step=step,
                    convergence_delta=error,
                    dataset_sha256=dataset.digest,
                )
            )
    return results
