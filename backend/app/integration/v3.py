"""Read Narinder's immutable V3 tiled package; never rebuild its grid."""

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
from pyproj import CRS

from .grid import Dataset


def read_v3(root):
    root = Path(root).resolve()
    checksums = json.loads((root / "SHA256_MANIFEST.json").read_text())["files"]
    consumed = {}

    def verified(relative):
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Package path escapes root")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksums.get(relative) != digest:
            raise ValueError(f"Package checksum mismatch: {relative}")
        consumed[relative] = digest
        return path

    # Verify every manifest-covered file, including evidence not consumed as features.
    for relative in checksums:
        verified(relative)
    consumed.clear()  # Preserve the historical feature snapshot identity.
    baseline = json.loads(verified("baseline/grid_metadata.json").read_text())
    verified(baseline["source"]["filename"])
    manifest = json.loads(verified("tile_manifest.json").read_text())
    crs = baseline["crs"]
    shape = CRS.from_wkt(crs["wkt"]).ellipsoid
    if (
        crs["frame"] != "MOON_ME / DE421"
        or shape.semi_major_metre != 1737400
        or shape.inverse_flattening != 0
    ):
        raise ValueError("V3 frame or spherical latitude mapping is unverified")
    if crs["longitude_convention"] != "east-positive [-180,180)":
        raise ValueError("Unsupported V3 longitude convention")
    rows = pq.read_table(verified("baseline/grid.parquet")).to_pylist()
    originals = {r["cell_id"]: r for r in rows}
    if len(originals) != len(rows):
        raise ValueError("Duplicate baseline cell IDs")
    neighbors = {}
    for edge in pq.read_table(verified("baseline/neighbors.parquet")).to_pylist():
        neighbors.setdefault(edge["cell_id"], []).append(edge["neighbor_id"])
    geometry_rows = pq.read_table(verified("baseline/grid_geometry.parquet")).to_pylist()
    geometries = {r["cell_id"]: r for r in geometry_rows}
    if len(geometries) != len(geometry_rows):
        raise ValueError("Duplicate geometry IDs")
    from .topology import validate_topology

    validate_topology(rows, geometries, neighbors, crs["wkt"])
    tile_ids = [t["tile_id"] for t in manifest["tiles"]]
    if len(set(tile_ids)) != len(tile_ids):
        raise ValueError("Duplicate tile IDs")
    cells = []
    for tile in manifest["tiles"]:
        tile_id = tile["tile_id"]
        tile_meta = json.loads(verified(f"tiles/{tile_id}/tile_metadata.json").read_text())
        if (
            tile_meta["frame"] != crs["frame"]
            or tile_meta["source_sha256"] != baseline["source"]["sha256"]
        ):
            raise ValueError("Inconsistent tile frame or source")
        path = verified(f"tiles/{tile_id}/cells.jsonl")
        derived = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if len(derived) != tile["cell_count"]:
            raise ValueError("Tile count mismatch")
        for row in derived:
            original = originals[row["cell_id"]]
            if any(original[k] != row[k] for k in original.keys() & row.keys()):
                raise ValueError("Original V3 attributes differ from tiled record")
            if set(neighbors.get(row["cell_id"], [])) != set(row["neighbor_ids"]):
                raise ValueError("Baseline neighbor mismatch")
            geometry = geometries[row["cell_id"]]
            if [geometry[k] for k in ("xmin_m", "ymin_m", "xmax_m", "ymax_m")] != row["bounds_m"]:
                raise ValueError("Baseline geometry bounds mismatch")
            for field in (
                "latitude",
                "longitude",
                "x_m",
                "y_m",
                "elevation_m",
                "slope_deg",
                "roughness_m",
            ):
                if original[field] != row[field]:
                    raise ValueError(f"Baseline mismatch: {field}")
            cells.append(
                dict(
                    row,
                    latitude_deg=row["latitude"],
                    longitude_deg=row["longitude"],
                    projected_x=row["x_m"],
                    projected_y=row["y_m"],
                    valid=row["data_valid"],
                    coverage_fraction=row["source_pixel_valid_fraction"],
                    quality=row["quality_status"],
                    uncertainty=dict(
                        elevation_uncertainty_m=row["elevation_uncertainty_m"],
                        lola_shot_count=row["lola_shot_count"],
                    ),
                    resolution_m=row["source_pixel_size_m"],
                    region="Site04",
                    neighbors=row["neighbor_ids"],
                    original_geometry_wkb_hex=geometry["geometry_wkb"].hex(),
                    geometry=dict(
                        type="Polygon",
                        coordinates=[row["footprint_projected_m"]],
                        coordinate_units="m",
                        crs=crs["wkt"],
                    ),
                    source=dict(
                        source_id=row["source_id"],
                        tile_id=tile_id,
                        raw_dem_sha256=baseline["source"]["sha256"],
                        tile_metadata=tile_meta,
                        calculation_method_version=row["calculation_method_version"],
                    ),
                )
            )
    if set(originals) != {c["cell_id"] for c in cells}:
        raise ValueError("Incomplete V3 cell ID coverage")
    metadata = dict(
        dataset_id=baseline["grid_configuration_id"]
        + "__tiles_"
        + manifest["tile_processing_version"],
        grid_version=baseline["grid_version"],
        processing_version=manifest["tile_processing_version"],
        scope="REGIONAL",
        coordinate_frame="MOON_ME_DE421",
        latitude_type="planetocentric_spherical",
        reference_radius_m=1737400,
        longitude_convention="east_positive_-180_180",
        elevation_datum=crs["vertical_reference"],
        projected_crs=crs["wkt"],
        source=dict(
            original_metadata=baseline,
            tile_manifest=manifest,
            verified_files=consumed,
            latitude_mapping="Identity on declared 1737400 m sphere; Horizons center radii checked before use",
        ),
        terrain_definition=json.dumps(baseline["methods"], sort_keys=True),
        resolution_m=baseline["source"]["native_pixel_m"],
        region="Site04",
        synthetic=False,
    )
    digest = hashlib.sha256(json.dumps(consumed, sort_keys=True).encode()).hexdigest()
    return Dataset(metadata, cells, digest)
