"""Read-only scientific queries over validated, immutable snapshots."""

import json
from functools import lru_cache
from pathlib import Path

from .features import FEATURES, SCALES, physical_vector
from .grid import describe, parse_id
from .storage import query, verified_files


class GlobalStore:
    def __init__(self, root):
        self.root = Path(root)

    @lru_cache(maxsize=8)
    def grid_files(self, nside):
        return verified_files(self.root / "global_grid" / f"nside={nside}")

    @lru_cache(maxsize=8)
    def feature_files(self, nside):
        manifests = sorted(
            (self.root / "feature_snapshots" / f"nside={nside}").glob("*/manifest.json")
        )
        if not manifests:
            return [], None
        if len(manifests) != 1:
            raise ValueError(
                "Multiple snapshots: configure a root with an explicit single active snapshot per level"
            )
        return verified_files(manifests[0].parent)

    def features(self, value):
        nside, pixel = parse_id(value)
        paths, manifest = self.feature_files(nside)
        if not paths:
            return dict(
                cell_id=value,
                measurements=[],
                missing_reason="NO_INGESTED_TERRAIN_AT_THIS_LEVEL",
                provenance=None,
            )
        selected = [
            p for p in paths if int(p.stem.split("-")[1]) <= pixel < int(p.stem.split("-")[1]) + 512
        ]
        rows = query(selected, "pixel = ?", [pixel], limit=1)
        return dict(
            cell_id=value,
            measurements=rows,
            missing_reason=None if rows else "NO_SOURCE_COVERAGE",
            provenance=manifest,
        )

    def regional(self, value):
        nside, _ = parse_id(value)
        path = self.root / "crosswalk" / f"nside-{nside}.parquet"
        if not path.exists():
            return []
        benchmark = json.loads((self.root / "grid-benchmark.json").read_text())
        from .storage import verify_path

        entry = next(row for row in benchmark["levels"] if row["nside"] == nside)
        verify_path(path, entry["crosswalk_sha256"])
        return query([path], "global_cell_id = ?", [value], limit=1000, order="regional_cell_id")

    def cell(self, value):
        info = describe(value)
        features = self.features(value)
        info.update(
            source_ids=sorted({row["source_id"] for row in features["measurements"]}),
            data_available=bool(features["measurements"]),
            regional_overlaps=self.regional(value),
        )
        return info

    def candidates(self, request):
        paths, manifest = self.feature_files(request.nside)
        if not paths:
            return [], None
        terms, args = ["TRUE"], []
        if request.bbox:
            west, south, east, north = request.bbox
            terms += ["latitude_deg BETWEEN ? AND ?"]
            args += [south, north]
            terms += [
                "longitude_deg BETWEEN ? AND ?"
                if west <= east
                else "(longitude_deg >= ? OR longitude_deg <= ?)"
            ]
            args += [west, east]
        for field, value in [
            ("slope_deg", request.maximum_slope_deg),
            ("roughness_m", request.maximum_roughness_m),
        ]:
            if value is not None:
                terms.append(f"{field} <= ?")
                args.append(value)
        terms.append("elevation_m_coverage >= ?")
        args.append(request.minimum_coverage)
        if request.quality is not None:
            terms.append("quality = ?")
            args.append(request.quality)
        return query(paths, " AND ".join(terms), args, request.limit, request.offset), manifest

    def similarity(self, request):
        nside, _ = parse_id(request.reference_cell_id)
        facts = self.features(request.reference_cell_id)
        if not facts["measurements"]:
            raise ValueError("Reference has no terrain measurements")
        reference = facts["measurements"][0]
        if any(reference[k] is None or reference[k + "_coverage"] < 1 for k in FEATURES):
            raise ValueError("Partial reference vector cannot support comparable distance")
        if not request.accept_unknown_uncertainty:
            raise ValueError(
                "Source uncertainty is unknown; explicit acceptance required for descriptive comparison"
            )
        paths, manifest = self.feature_files(nside)
        # Exact search against one compatible immutable source snapshot; no ANN
        # or global in-memory vector matrix. The source, method and resolution
        # are identical for every row in this snapshot.
        expression = " + ".join(
            f"pow(({k} - {float(reference[k])!r}) / {s}, 2)" for k, s in zip(FEATURES, SCALES)
        )
        where = "cell_id != ? AND " + " AND ".join(
            f"{k} IS NOT NULL AND {k}_coverage = 1" for k in FEATURES
        )
        rows = query(
            paths,
            where,
            [request.reference_cell_id],
            request.maximum_results,
            columns=f"*, sqrt({expression}) AS distance",
            order="distance, cell_id",
        )
        for row in rows:
            row["feature_differences"] = {k: row[k] - reference[k] for k in FEATURES}
        return dict(
            reference_cell_id=request.reference_cell_id,
            matches=rows,
            normalization_version="physical-scales-v1",
            snapshot_id=manifest["snapshot_id"],
            scope="Exact search within one source, method, resolution and snapshot; uncertainty unknown; not a safety ranking",
        )

    def vector(self, value):
        facts = self.features(value)
        return physical_vector(facts["measurements"][0]) if facts["measurements"] else None
