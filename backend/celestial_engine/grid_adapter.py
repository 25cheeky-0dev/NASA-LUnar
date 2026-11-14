"""Explicit grid contract; terrain elevations are never silently substituted."""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictBool, StrictStr

from .schemas import EphemerisRequest, StrictModel


class GridMetadata(StrictModel):
    coordinate_frame: Literal["MOON_ME_DE421"]
    longitude_convention: Literal["east_positive_0_360"]
    latitude_type: Literal["planetodetic"]
    elevation_units: Literal["m"]
    elevation_datum: str = Field(min_length=1)
    source: str = Field(min_length=1)
    # True is an operator declaration requiring dataset evidence, not an automatic inference.
    elevation_matches_horizons_reference: StrictBool = False


class GridCell(StrictModel):
    model_config = {"extra": "allow", "allow_inf_nan": False}
    cell_id: StrictStr = Field(min_length=1)
    latitude_deg: float = Field(ge=-90, le=90)
    longitude_east_deg: float = Field(ge=0, lt=360)
    elevation_m: float
    slope_deg: float = Field(ge=0, le=90)
    roughness_m: float = Field(ge=0)
    valid: StrictBool


def read_grid(path):
    """JSON {metadata,cells}, or Parquet with wispr_grid_metadata schema metadata."""
    path = Path(path)
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        table = pq.read_table(path)
        metadata = json.loads((table.schema.metadata or {})[b"wispr_grid_metadata"])
        rows = table.to_pylist()
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        metadata, rows = payload["metadata"], payload["cells"]
    return GridMetadata.model_validate(metadata), [GridCell.model_validate(row) for row in rows]


class GridAdapter:
    def __init__(self, service, *, max_cells=16, max_samples=20000):
        if not 1 <= max_cells <= 64 or not 2 <= max_samples <= 100000:
            raise ValueError("Invalid grid budget")
        self.service, self.max_cells, self.max_samples = service, max_cells, max_samples

    def process(self, cells, metadata, template, *, batch_size=4, use_grid_elevation=False):
        """Validate the whole bounded job before making sequential queries."""
        if not 1 <= batch_size <= self.max_cells or len(cells) > self.max_cells:
            raise ValueError("Grid exceeds explicit bounded cell budget")
        metadata = GridMetadata.model_validate(metadata)
        cells = [GridCell.model_validate(cell) for cell in cells]
        if len({cell.cell_id for cell in cells}) != len(cells):
            raise ValueError("Duplicate cell IDs")
        if sum(cell.valid for cell in cells) * len(template.timestamps()) > self.max_samples:
            raise ValueError("Grid exceeds total sample budget")
        if use_grid_elevation and (
            not metadata.elevation_matches_horizons_reference
            or metadata.elevation_datum != "horizons_lunar_reference"
        ):
            raise ValueError("Grid vertical datum has not been verified compatible with Horizons")
        requests = []
        for cell in cells:
            if cell.valid:
                values = template.model_dump() | dict(
                    latitude_deg=cell.latitude_deg,
                    longitude_east_deg=cell.longitude_east_deg,
                )
                if use_grid_elevation:
                    values["altitude_km"] = cell.elevation_m / 1000
                requests.append((cell, EphemerisRequest.model_validate(values)))
        results = []
        for start in range(0, len(requests), batch_size):
            for cell, request in requests[start : start + batch_size]:
                result = self.service.ephemeris(request)
                results.append(
                    dict(
                        cell_id=cell.cell_id,
                        ephemeris=result,
                        grid_elevation_applied=use_grid_elevation,
                        grid_metadata=metadata.model_dump(),
                    )
                )
        return dict(
            results=results,
            skipped_cell_ids=[cell.cell_id for cell in cells if not cell.valid],
        )
