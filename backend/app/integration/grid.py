"""Version-neutral JSON/Parquet grid contract and physical vector index."""

import hashlib
import json
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import Field, StrictStr, model_validator

from celestial_engine.schemas import StrictModel

FEATURES = ["elevation_m", "slope_deg", "roughness_m"]
UNITS = dict(zip(FEATURES, ["m", "degree", "m"]))
# Fixed physical scales, not a safety score or dataset-dependent fitted statistics.
NORMALIZATION = dict(
    version="physical-scales-v1",
    strategy="x / scale; no clipping or imputation",
    offsets=[0.0, 0.0, 0.0],
    scales=[1000.0, 10.0, 10.0],
    units=UNITS,
)


class Metadata(StrictModel):
    dataset_id: str = Field(min_length=1)
    grid_version: str = Field(min_length=1)
    processing_version: str | None = None
    reference_radius_m: float | None = Field(default=None, gt=0)
    scope: Literal["GLOBAL", "REGIONAL"]
    coordinate_frame: str
    latitude_type: str
    longitude_convention: Literal[
        "east_positive_0_360", "east_positive_-180_180", "west_positive_0_360"
    ]
    elevation_units: Literal["m"] = "m"
    elevation_datum: str
    projected_crs: str | None = None
    source: dict
    terrain_definition: str = Field(min_length=1)
    resolution_m: float | None = Field(default=None, gt=0)
    region: str | None = None
    synthetic: bool = False


class Cell(StrictModel):
    model_config = {"extra": "allow", "allow_inf_nan": False}
    cell_id: StrictStr = Field(min_length=1)
    latitude_deg: float = Field(ge=-90, le=90)
    longitude_deg: float = Field(ge=-180, le=360)
    projected_x: float | None = None
    projected_y: float | None = None
    elevation_m: float | None = None
    slope_deg: float | None = Field(default=None, ge=0, le=90)
    roughness_m: float | None = Field(default=None, ge=0)
    valid: bool
    coverage_fraction: float | None = Field(default=None, ge=0, le=1)
    quality: str = "UNKNOWN"
    uncertainty: dict = Field(default_factory=dict)
    source: dict = Field(default_factory=dict)
    resolution_m: float | None = Field(default=None, gt=0)
    region: str | None = None
    neighbors: list[StrictStr] = Field(default_factory=list)
    geometry: dict | None = None


class Filters(StrictModel):
    region: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    minimum_coverage: float = Field(default=1, ge=0, le=1)
    qualities: list[str] = Field(default_factory=lambda: ["VERIFIED"])
    maximum_slope_deg: float | None = Field(default=None, ge=0, le=90)
    maximum_roughness_m: float | None = Field(default=None, ge=0)
    minimum_elevation_m: float | None = None
    maximum_elevation_m: float | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def bounds(self):
        if self.bbox:
            west, south, east, north = self.bbox
            if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
                raise ValueError(
                    "bbox uses ordered east-positive [-180,180] coordinates; split antimeridian queries"
                )
        if (
            self.minimum_elevation_m is not None
            and self.maximum_elevation_m is not None
            and self.minimum_elevation_m > self.maximum_elevation_m
        ):
            raise ValueError("Inverted elevation bounds")
        return self


class Dataset:
    def __init__(self, metadata, cells, digest):
        self.metadata = Metadata.model_validate(metadata)
        self.cells = [Cell.model_validate(c) for c in cells]
        self.by_id = {c.cell_id: i for i, c in enumerate(self.cells)}
        if len(self.by_id) != len(self.cells):
            raise ValueError("Duplicate cell IDs")
        for cell in self.cells:
            lon = cell.longitude_deg
            if self.metadata.longitude_convention.endswith("0_360") and not 0 <= lon < 360:
                raise ValueError("Longitude outside declared convention")
            if (
                self.metadata.longitude_convention == "east_positive_-180_180"
                and not -180 <= lon <= 180
            ):
                raise ValueError("Longitude outside declared convention")
        self.digest = digest
        self.raw = np.array(
            [
                [getattr(c, f) if getattr(c, f) is not None else np.nan for f in FEATURES]
                for c in self.cells
            ],
            dtype=np.float64,
        ).reshape((-1, 3))
        self.normalized = self.raw / np.array(NORMALIZATION["scales"])

    @classmethod
    def read(cls, path):
        path = Path(path)
        if path.suffix == ".parquet":
            import pyarrow.parquet as pq

            table = pq.read_table(path)
            meta = json.loads((table.schema.metadata or {})[b"wispr_grid_metadata"])
            rows = table.to_pylist()
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            meta, rows = payload["metadata"], payload["cells"]
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return cls(meta, rows, digest)

    def cell(self, cell_id):
        return self.cells[self.by_id[cell_id]]

    def east_longitude(self, cell):
        return (
            -cell.longitude_deg
            if self.metadata.longitude_convention.startswith("west")
            else cell.longitude_deg
        ) % 360

    def evidence(self, cell):
        return dict(
            resolution_m=cell.resolution_m or self.metadata.resolution_m,
            terrain_definition=self.metadata.terrain_definition,
            elevation_datum=self.metadata.elevation_datum,
            coordinate_frame=self.metadata.coordinate_frame,
            quality=cell.quality,
            uncertainty=cell.uncertainty,
            coverage_fraction=cell.coverage_fraction,
            synthetic=self.metadata.synthetic,
        )

    def vector(self, cell_id):
        i = self.by_id[cell_id]

        def clean(row):
            return [float(x) if np.isfinite(x) else None for x in row]

        return dict(
            cell_id=cell_id,
            grid_version=self.metadata.grid_version,
            dataset_id=self.metadata.dataset_id,
            feature_names=FEATURES,
            units=UNITS,
            raw=clean(self.raw[i]),
            normalized=clean(self.normalized[i]),
            missing_mask=np.isnan(self.raw[i]).tolist(),
            normalization=NORMALIZATION,
            quality=self.evidence(self.cells[i]),
            valid=self.cells[i].valid,
            provenance=dict(
                dataset_sha256=self.digest,
                dataset_source=self.metadata.source,
                cell_source=self.cells[i].source,
            ),
        )

    def select(self, filters):
        mask = np.isfinite(self.raw).all(axis=1)
        reasons = {}
        for i, cell in enumerate(self.cells):
            fail = []
            if not mask[i]:
                fail.append("MISSING_TERRAIN")
            if not cell.valid:
                fail.append("INVALID_CELL")
            if cell.quality not in filters.qualities:
                fail.append("QUALITY")
            if cell.coverage_fraction is None or cell.coverage_fraction < filters.minimum_coverage:
                fail.append("COVERAGE")
            if filters.region and (cell.region or self.metadata.region) != filters.region:
                fail.append("REGION")
            if filters.bbox:
                w, s, e, n = filters.bbox
                lon = (self.east_longitude(cell) + 180) % 360 - 180
                if not (w <= lon <= e and s <= cell.latitude_deg <= n):
                    fail.append("BBOX")
            for field, threshold, maximum in [
                ("slope_deg", filters.maximum_slope_deg, True),
                ("roughness_m", filters.maximum_roughness_m, True),
                ("elevation_m", filters.maximum_elevation_m, True),
                ("elevation_m", filters.minimum_elevation_m, False),
            ]:
                value = getattr(cell, field)
                if threshold is not None and (
                    value is None or (value > threshold if maximum else value < threshold)
                ):
                    fail.append(field.upper() + "_CONSTRAINT")
            mask[i] = not fail
            reasons[cell.cell_id] = fail
        ids = sorted(self.cells[i].cell_id for i in np.flatnonzero(mask))
        return dict(
            cell_ids=ids[filters.offset : filters.offset + filters.limit],
            total=len(ids),
            offset=filters.offset,
            limit=filters.limit,
        ), reasons

    def similarity(self, cell_id, limit=20):
        cell = self.cell(cell_id)
        if not cell.valid or not np.isfinite(self.normalized[self.by_id[cell_id]]).all():
            raise ValueError("Complete valid terrain required")
        evidence = self.evidence(cell)
        if (
            evidence["resolution_m"] is None
            or cell.quality != "VERIFIED"
            or not cell.uncertainty
            or cell.coverage_fraction != 1
        ):
            raise ValueError(
                "Resolution, full coverage, verified quality and uncertainty required for similarity"
            )
        matches = []
        for other in self.cells:
            if other.cell_id == cell_id or not other.valid or self.evidence(other) != evidence:
                continue
            row = self.normalized[self.by_id[other.cell_id]]
            if np.isfinite(row).all():
                matches.append(
                    dict(
                        cell_id=other.cell_id,
                        normalized_euclidean_distance=float(
                            np.linalg.norm(row - self.normalized[self.by_id[cell_id]])
                        ),
                    )
                )
        return dict(
            reference_cell_id=cell_id,
            metric="Euclidean physical-scales-v1; descriptive, not safety",
            comparability=evidence,
            matches=sorted(
                matches, key=lambda x: (x["normalized_euclidean_distance"], x["cell_id"])
            )[:limit],
        )


class Registry:
    def __init__(self, root):
        self.datasets = {}
        self.errors = []
        root = Path(root)
        packages = (
            [root]
            if (root / "tile_manifest.json").exists()
            else [p.parent for p in root.rglob("tile_manifest.json")]
        )
        for package in packages:
            try:
                from .v3 import read_v3

                d = read_v3(package)
                if d.metadata.dataset_id in self.datasets:
                    raise ValueError("Duplicate dataset ID")
                self.datasets[d.metadata.dataset_id] = d
            except (ValueError, KeyError, OSError) as exc:
                self.errors.append(dict(file=str(package), error=str(exc)))
        for path in sorted(Path(root).rglob("*")):
            if any(path.is_relative_to(package) for package in packages):
                continue
            if path.suffix not in (".json", ".parquet"):
                continue
            try:
                dataset = Dataset.read(path)
                key = dataset.metadata.dataset_id
                if key in self.datasets:
                    raise ValueError("Duplicate dataset_id; use version-specific IDs")
                self.datasets[key] = dataset
            except (ValueError, KeyError, OSError) as exc:
                self.errors.append(dict(file=path.name, error=str(exc)))
