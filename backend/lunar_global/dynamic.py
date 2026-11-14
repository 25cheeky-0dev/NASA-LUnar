"""Bounded cell-reference adapter to the existing validated analysis engine."""

import hashlib
import json
from types import SimpleNamespace

from app.integration.api import engine
from app.integration.engine import AnalysisEngine
from app.integration.grid import Dataset

from .features import METHOD
from .grid import FRAME, GRID_VERSION, RADIUS_M, describe


def selected_engine(store, request):
    if request.dataset_id != "GLOBAL_SELECTED":
        return engine()
    rows, sources = [], {}
    for value in request.cell_ids:
        geo = describe(value)
        facts = store.features(value)
        measurement = facts["measurements"][0] if facts["measurements"] else {}
        if measurement:
            sources[measurement["source_id"]] = facts["provenance"]["source"]
        rows.append(
            dict(
                cell_id=value,
                latitude_deg=geo["latitude_deg"],
                longitude_deg=geo["longitude_deg"],
                elevation_m=measurement.get("elevation_m"),
                slope_deg=measurement.get("slope_deg"),
                roughness_m=measurement.get("roughness_m"),
                valid=True,
                coverage_fraction=measurement.get("elevation_m_coverage", 0),
                quality=measurement.get("quality", "NO_TERRAIN_EVIDENCE"),
                source={"measurement": measurement},
                resolution_m=measurement.get("native_resolution_m"),
                uncertainty={"elevation_uncertainty_m": None},
            )
        )
    meta = dict(
        dataset_id="GLOBAL_SELECTED",
        grid_version=GRID_VERSION,
        scope="GLOBAL",
        coordinate_frame=FRAME,
        latitude_type="planetocentric_spherical",
        reference_radius_m=RADIUS_M,
        longitude_convention="east_positive_0_360",
        elevation_datum="Height above 1737400 m reference sphere",
        terrain_definition=METHOD,
        source=sources,
    )
    digest = hashlib.sha256(
        json.dumps(dict(metadata=meta, cells=rows), sort_keys=True).encode()
    ).hexdigest()
    dataset = Dataset(meta, rows, digest)
    return AnalysisEngine(
        SimpleNamespace(datasets={"GLOBAL_SELECTED": dataset}), celestial=engine().celestial
    )
