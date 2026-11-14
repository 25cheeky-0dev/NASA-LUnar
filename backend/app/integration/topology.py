"""Selected topology safeguards from the alternate engine, using canonical data."""

import math

from pyproj import CRS, Transformer
from shapely import from_wkb
from shapely.errors import GEOSException


def validate_topology(rows, geometries, neighbors, wkt):
    ids = {r["cell_id"] for r in rows}
    if set(geometries) != ids or not set(neighbors) <= ids:
        raise ValueError("Geometry/topology IDs differ from baseline")
    crs = CRS.from_wkt(wkt)
    transform = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
    polygons = {}
    for row in rows:
        key = row["cell_id"]
        g = geometries[key]
        try:
            polygon = from_wkb(g["geometry_wkb"])
        except GEOSException as exc:
            raise ValueError("Corrupt original polygon") from exc
        if polygon.geom_type != "Polygon" or not polygon.is_valid or polygon.is_empty:
            raise ValueError("Invalid original polygon")
        if any(
            abs(a - b) > 1e-6
            for a, b in zip(
                polygon.bounds, [g[k] for k in ("xmin_m", "ymin_m", "xmax_m", "ymax_m")]
            )
        ):
            raise ValueError("Polygon bounds mismatch")
        x, y = transform.transform(row["longitude"], row["latitude"])
        if not math.isfinite(x + y) or math.hypot(x - row["x_m"], y - row["y_m"]) > 1e-5:
            raise ValueError("Projection roundtrip mismatch")
        if math.hypot(polygon.centroid.x - row["x_m"], polygon.centroid.y - row["y_m"]) > 1e-5:
            raise ValueError("Polygon center mismatch")
        polygons[key] = polygon
    for key, links in neighbors.items():
        if len(set(links)) != len(links) or key in links or not set(links) <= ids:
            raise ValueError("Invalid or duplicate neighbor")
        for other in links:
            if key not in neighbors.get(other, []):
                raise ValueError("Nonreciprocal neighbor")
            if polygons[key].boundary.intersection(polygons[other].boundary).length <= 0:
                raise ValueError("Neighbors do not share an edge")
