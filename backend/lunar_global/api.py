"""Additive, bounded API alongside the existing authoritative analysis engine."""

import json
import os
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.integration import contracts
from app.integration.api import _gate, evaluate
from app.integration.contracts import ScienceError
from app.integration.engine import Scenario

from .dynamic import selected_engine
from .grid import LEVELS, describe, hpx, lookup
from .service import GlobalStore
from .storage import query, sha256


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Crosswalk(Model):
    dataset_id: str
    regional_cell_id: str
    global_cell_id: str
    overlap_fraction: float = Field(ge=0, le=1.000001)
    method: str
    boundary_step: int
    convergence_delta: float
    dataset_sha256: str


class GlobalCell(Model):
    cell_id: str
    nside: int
    pixel: int
    level: int
    latitude_deg: float
    longitude_deg: float
    parent_id: str | None
    children: list[str]
    neighbors: list[str]
    area_m2: float
    boundary_lonlat: list[tuple[float, float]]
    boundary_step: int
    boundary_method: str
    coordinate_frame: str
    reference_radius_m: float
    latitude_type: str
    longitude_convention: str
    grid_version: str
    source_ids: list[str]
    data_available: bool
    regional_overlaps: list[Crosswalk]


class Page(Model):
    records: list[dict]
    offset: int
    limit: int
    scope: str


class TerrainMeasurement(Model):
    cell_id: str
    pixel: int
    latitude_deg: float
    longitude_deg: float
    source_id: str
    snapshot_id: str
    quality: str
    native_resolution_m: float
    effective_analysis_resolution_m: float
    method: str
    uncertainty: float | None
    elevation_m: float | None
    slope_deg: float | None
    roughness_m: float | None
    elevation_m_coverage: float = Field(ge=0, le=1)
    slope_deg_coverage: float = Field(ge=0, le=1)
    roughness_m_coverage: float = Field(ge=0, le=1)
    sampled_minimum_elevation_m: float | None
    sampled_maximum_elevation_m: float | None
    elevation_variability_m: float | None
    sampled_source_pixel_count: float
    raw_values: list[float | None] = Field(min_length=3, max_length=3)
    normalized_values: list[float | None] = Field(min_length=3, max_length=3)
    missing_mask: list[bool] = Field(min_length=3, max_length=3)


class TerrainPage(Model):
    records: list[TerrainMeasurement]
    offset: int
    limit: int
    scope: str


class FeatureResponse(Model):
    cell_id: str
    measurements: list[TerrainMeasurement]
    missing_reason: str | None
    provenance: dict | None


class ThermalResponse(Model):
    measurements: list[dict]
    missing_reason: str | None
    source: dict | None
    support: str | None = None


class Candidates(Model):
    nside: Literal[64, 128, 256] = 128
    bbox: tuple[float, float, float, float] | None = None
    maximum_slope_deg: float | None = Field(default=None, ge=0, le=90)
    maximum_roughness_m: float | None = Field(default=None, ge=0)
    minimum_coverage: float = Field(default=1, ge=0, le=1)
    quality: str | None = None
    offset: int = Field(default=0, ge=0, le=4000000)
    limit: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def bounds(self):
        if self.bbox:
            west, south, east, north = self.bbox
            if not (0 <= west <= 360 and 0 <= east <= 360 and -90 <= south <= north <= 90):
                raise ValueError(
                    "bbox requires east-positive [0,360] west/east and ordered south/north"
                )
        return self


class Similarity(Model):
    reference_cell_id: str
    feature_set: Literal["terrain-v1"] = "terrain-v1"
    normalization_version: Literal["physical-scales-v1"] = "physical-scales-v1"
    maximum_results: int = Field(default=10, ge=1, le=100)
    accept_unknown_uncertainty: bool = False


class Retrieval(Model):
    question: str = Field(min_length=1, max_length=2000)
    maximum_results: int = Field(default=10, ge=1, le=50)


@lru_cache(maxsize=1)
def optional_status():
    from .spectral import STATUS

    return STATUS


class VectorResponse(Model):
    cell_id: str
    vector: dict | None


class SimilarityResponse(Model):
    reference_cell_id: str
    matches: list[dict]
    normalization_version: str
    snapshot_id: str
    scope: str


class GlobalScenario(Scenario):
    dataset_id: str = "GLOBAL_SELECTED"


class GlobalDelay(GlobalScenario):
    original_cell_id: str = Field(min_length=1)


router = APIRouter(
    prefix="/api/v1/science/global",
    tags=["global-science"],
    responses={
        404: {"model": ScienceError, "description": "Not Found"},
        422: {"model": ScienceError, "description": "Invalid scientific or schema request"},
        429: {"model": ScienceError, "description": "Analysis capacity exceeded"},
        503: {"model": ScienceError, "description": "Scientific source unavailable"},
    },
)


@lru_cache(maxsize=1)
def store():
    return GlobalStore(os.getenv("WISPR_GLOBAL_ROOT", "data/lunar-v1"))


def call(action, *args, **kwargs):
    try:
        return action(*args, **kwargs)
    except FileNotFoundError as exc:
        raise HTTPException(503, "Required global snapshot unavailable") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/levels", response_model=Page)
def levels():
    rows = []
    for nside in LEVELS:
        exists = (store().root / "global_grid" / f"nside={nside}" / "manifest.json").exists()
        rows.append(
            dict(
                nside=nside,
                cells=int(hpx(nside).npix),
                index_built=exists,
                terrain_available=bool(store().feature_files(nside)[0]),
            )
        )
    return dict(
        records=rows,
        offset=0,
        limit=4,
        scope="Spatial index availability is separate from measurements",
    )


@router.get("/cells/lookup", response_model=GlobalCell)
def locate(latitude: float = Query(ge=-90, le=90), longitude: float = Query(), nside: int = 128):
    return call(store().cell, call(lookup, latitude, longitude, nside))


@router.get("/cells", response_model=Page)
def cells(
    nside: int = 128,
    offset: int = Query(0, ge=0, le=4000000),
    limit: int = Query(100, ge=1, le=1000),
):
    call(hpx, nside)
    paths, _ = call(store().grid_files, nside)
    return dict(
        records=query(paths, limit=limit, offset=offset),
        offset=offset,
        limit=limit,
        scope="Global cell centers; boundary geometry generated on selection",
    )


@router.get("/cells/{cell_id}", response_model=GlobalCell)
def cell(cell_id: str):
    return call(store().cell, cell_id)


@router.get("/cells/{cell_id}/neighbors", response_model=Page)
def neighbors(cell_id: str):
    info = call(describe, cell_id)
    return dict(
        records=[dict(cell_id=value) for value in info["neighbors"]],
        offset=0,
        limit=8,
        scope="HEALPix edge/corner neighbors",
    )


@router.get("/cells/{cell_id}/features", response_model=FeatureResponse)
def features(cell_id: str):
    return call(store().features, cell_id)


@router.get("/cells/{cell_id}/thermal", response_model=ThermalResponse)
def thermal(cell_id: str, local_time_bin: int = Query(ge=0, le=95)):
    from .thermal import thermal_context

    geo = call(describe, cell_id)
    return call(
        thermal_context, store().root, geo["latitude_deg"], geo["longitude_deg"], local_time_bin
    )


@router.get("/cells/{cell_id}/vectors", response_model=VectorResponse)
def vectors(cell_id: str):
    return dict(cell_id=cell_id, vector=call(store().vector, cell_id))


@router.get("/cells/{cell_id}/sources", response_model=Page)
def sources(cell_id: str):
    result = call(store().features, cell_id)
    rows = [result["provenance"]["source"]] if result["provenance"] else []
    from .imagery import context

    geo = call(describe, cell_id)
    imagery = call(context, store().root, geo["latitude_deg"], geo["longitude_deg"])
    if imagery:
        rows.append(imagery)
    return dict(records=rows, offset=0, limit=100, scope="Actual ingested source registrations")


@router.post("/retrieve", response_model=Page)
def retrieve(request: Retrieval):
    from .retrieval import keyword_sources

    return dict(
        records=keyword_sources(store().root, request.question, request.maximum_results),
        offset=0,
        limit=request.maximum_results,
        scope="Source-document keyword search; embeddings unconfigured; no physical recommendation",
    )


@router.get("/optional-sources", response_model=Page)
def optional_sources():
    return dict(
        records=[
            optional_status(),
            dict(
                source="Moon Trek",
                status="OPTIONAL_NOT_CONFIGURED",
                documentation="https://trek.nasa.gov/tiles/apidoc/",
                reason="Documented WMTS available; no specific layer capability bound",
            ),
        ],
        offset=0,
        limit=10,
        scope="Explicit optional-source availability",
    )


@router.post("/candidates", response_model=TerrainPage)
def candidates(request: Candidates):
    rows, _ = call(store().candidates, request)
    return dict(
        records=rows,
        offset=request.offset,
        limit=request.limit,
        scope="Center-in-bbox retrieval with source-native derivatives; no implicit safety thresholds",
    )


@router.post("/similarity", response_model=SimilarityResponse)
def similarity(request: Similarity):
    if not _gate.acquire(blocking=False):
        raise HTTPException(429, "Scientific analysis capacity reached; retry later")
    try:
        return call(store().similarity, request)
    finally:
        _gate.release()


@router.get("/regional/{regional_cell_id}/crosswalk", response_model=Page)
def regional_crosswalk(regional_cell_id: str, nside: int = 128):
    call(hpx, nside)
    call(store().regional, f"MOON:HPX:NESTED:{nside}:0")  # Verify crosswalk before reverse query.
    path = store().root / "crosswalk" / f"nside-{nside}.parquet"
    rows = call(query, [path], "regional_cell_id = ?", [regional_cell_id], order="global_cell_id")
    return dict(
        records=rows,
        offset=0,
        limit=100,
        scope="Preserved regional identity; projected overlap fractions",
    )


@router.get("/tiles/{level}/{tile_id}", response_model=Page)
def tile(level: int, tile_id: int):
    call(hpx, level)
    if tile_id < 0 or tile_id * 64 >= hpx(level).npix:
        raise HTTPException(422, "Tile outside grid")
    rows = [
        describe(f"MOON:HPX:NESTED:{level}:{p}", step=4)
        for p in range(tile_id * 64, min((tile_id + 1) * 64, int(hpx(level).npix)))
    ]
    return dict(
        records=rows,
        offset=tile_id * 64,
        limit=64,
        scope="Bounded native lon/lat rings; consumers must split longitude wrap",
    )


@router.post(
    "/analysis", response_model=contracts.AnalysisResponse, response_model_exclude_unset=True
)
def analysis(request: GlobalScenario):
    service = call(selected_engine, store(), request)
    return evaluate(request, analysis_engine=service)


@router.post("/delay", response_model=contracts.DelayResponse, response_model_exclude_unset=True)
def delay(request: GlobalDelay):
    if not _gate.acquire(blocking=False):
        raise HTTPException(429, "Scientific analysis capacity reached; retry later")
    try:
        scenario = GlobalScenario.model_validate(request.model_dump(exclude={"original_cell_id"}))
        service = call(selected_engine, store(), scenario)
        return call(service.delay, scenario, request.original_cell_id)
    finally:
        _gate.release()


@router.post("/source-overlap", response_model=Page)
def source_overlap(request: Candidates):
    if request.limit > 50:
        raise HTTPException(422, "Source overlap is limited to 50 cells per page")
    from .imagery import context

    rows, _ = call(store().candidates, request)
    result = []
    for row in rows:
        image = call(context, store().root, row["latitude_deg"], row["longitude_deg"])
        if image and image["value"] is not None:
            result.append(
                dict(
                    cell_id=row["cell_id"],
                    terrain=row,
                    imagery=image,
                    policy="Separate spatially associated products; image DN is not terrain physics",
                )
            )
    return dict(
        records=result,
        offset=request.offset,
        limit=request.limit,
        scope="LOLA footprint aggregate plus LROC source pixel at center; historical products, not simultaneous observations",
    )


@router.get("/layers", response_model=Page)
def layers():
    path = store().root / "visualization_tiles" / "layers.json"
    rows = json.loads(path.read_text()) if path.exists() else []
    return dict(
        records=rows,
        offset=0,
        limit=100,
        scope="Stored measurement rendering; unavailable layers remain explicit",
    )


@router.get("/layer-images/{layer_id}", response_class=FileResponse)
def layer_image(layer_id: str):
    entries = layers()["records"]
    row = next(
        (r for r in entries if r["layer_id"] == layer_id and r["status"] == "AVAILABLE"), None
    )
    if not row:
        raise HTTPException(404, "Layer unavailable")
    path = store().root / "visualization_tiles" / row["file"]
    if sha256(path) != row["sha256"]:
        raise HTTPException(503, "Layer checksum mismatch")
    return FileResponse(path, media_type="image/png")
