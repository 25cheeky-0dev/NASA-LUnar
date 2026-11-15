"""Additive bounded API; existing v1 response contracts are unchanged."""

import hashlib
import json
import os
import threading
from collections import OrderedDict
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query
from pydantic import Field

from . import contracts as contract
from .engine import AnalysisEngine, Scenario
from .grid import Filters, Registry

router = APIRouter(
    prefix="/api/v1/science",
    tags=["unified-science"],
    responses={
        code: {"model": contract.ScienceError, "description": description}
        for code, description in (
            (404, "Not Found"),
            (422, "Invalid scientific or schema request"),
            (429, "Analysis capacity exceeded"),
        )
    },
)
_gate = threading.BoundedSemaphore(2)
_lock = threading.Lock()
scenarios = OrderedDict()


@lru_cache(maxsize=1)
def engine():
    return AnalysisEngine(Registry(os.getenv("WISPR_GRID_DIR", "data/grids")))


def dataset(dataset_id):
    try:
        return engine().registry.datasets[dataset_id]
    except KeyError as exc:
        raise HTTPException(404, "Dataset not found; configure WISPR_GRID_DIR") from exc


@router.get("/datasets", response_model=contract.DatasetPage, response_model_exclude_unset=True)
def datasets(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    registry = engine().registry
    values = sorted(registry.datasets.values(), key=lambda d: d.metadata.dataset_id)
    return dict(
        datasets=[
            dict(d.metadata.model_dump(), cell_count=len(d.cells), sha256=d.digest)
            for d in values[offset : offset + limit]
        ],
        total=len(values),
        offset=offset,
        limit=limit,
        ingestion_errors=registry.errors[:100],
        status="AVAILABLE" if values else "MISSING_GRID_ASSETS",
    )


@router.get(
    "/datasets/{dataset_id}/cells",
    response_model=contract.CellPage,
    response_model_exclude_unset=True,
)
def cells(dataset_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    d = dataset(dataset_id)
    return dict(
        cells=[c.model_dump() for c in d.cells[offset : offset + limit]],
        total=len(d.cells),
        offset=offset,
        limit=limit,
    )


@router.get(
    "/datasets/{dataset_id}/cells/{cell_id}",
    response_model=contract.CellResponse,
    response_model_exclude_unset=True,
)
def cell(dataset_id: str, cell_id: str):
    d = dataset(dataset_id)
    try:
        return dict(
            cell=d.cell(cell_id).model_dump(),
            metadata=d.metadata.model_dump(),
            dataset_sha256=d.digest,
        )
    except KeyError as exc:
        raise HTTPException(404, "Unknown cell ID") from exc


@router.get(
    "/datasets/{dataset_id}/vectors/{cell_id}",
    response_model=contract.StaticVector,
    response_model_exclude_unset=True,
)
def vector(dataset_id: str, cell_id: str):
    try:
        return dataset(dataset_id).vector(cell_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown cell ID") from exc


@router.get(
    "/datasets/{dataset_id}/similarity/{cell_id}",
    response_model=contract.SimilarityResponse,
    response_model_exclude_unset=True,
)
def similarity(
    dataset_id: str,
    cell_id: str,
    limit: int = Query(20, ge=1, le=1000),
    accept_unknown_uncertainty: bool = False,
):
    try:
        return dataset(dataset_id).similarity(
            cell_id, limit, accept_unknown_uncertainty=accept_unknown_uncertainty
        )
    except KeyError as exc:
        raise HTTPException(404, "Unknown cell ID") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post(
    "/datasets/{dataset_id}/candidates",
    response_model=contract.CandidateResponse,
    response_model_exclude_unset=True,
)
def candidates(dataset_id: str, filters: Filters):
    selected, _ = dataset(dataset_id).select(filters)
    return dict(
        selected,
        filters=filters.model_dump(),
        units={"slope": "degree", "roughness": "m", "elevation": "m"},
        ordering="Original cell ID ascending; no implicit safety thresholds",
    )


def evaluate(request, analysis_engine=None):
    if not _gate.acquire(blocking=False):
        raise HTTPException(429, "Scientific analysis capacity reached; retry later")
    try:
        result = (analysis_engine or engine()).analyze(request)
        key = hashlib.sha256(
            json.dumps(
                dict(
                    request=request.model_dump(mode="json"),
                    dataset=result["dataset_sha256"],
                    evidence=[
                        dict(
                            queries=r["dynamic_vector"]["provenance"].get("queries", {}),
                            horizon=r["dynamic_vector"]["horizon"],
                        )
                        for r in result["results"]
                        if r["dynamic_vector"]
                    ],
                ),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        result["scenario_id"] = key
        with _lock:
            scenarios[key] = result
            scenarios.move_to_end(key)
            while len(scenarios) > 16:
                scenarios.popitem(last=False)
        return result
    except KeyError as exc:
        raise HTTPException(404, "Unknown dataset or cell ID") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        _gate.release()


@router.post(
    "/analysis", response_model=contract.AnalysisResponse, response_model_exclude_unset=True
)
def analysis(request: Scenario):
    return evaluate(request)


@router.post(
    "/celestial", response_model=contract.AnalysisResponse, response_model_exclude_unset=True
)
def celestial(request: Scenario):
    return evaluate(request)


@router.post("/ranking", response_model=contract.RankingResponse, response_model_exclude_unset=True)
def ranking(request: Scenario):
    result = evaluate(request)
    return dict(
        scenario_id=result["scenario_id"],
        comparison=result["comparison"],
        results=result["results"],
        scope=result["scope"],
    )


@router.get(
    "/scenarios/{scenario_id}",
    response_model=contract.ScenarioResponse,
    response_model_exclude_unset=True,
)
def dynamic_vectors(scenario_id: str):
    with _lock:
        result = scenarios.get(scenario_id)
        if result is None:
            raise HTTPException(404, "Scenario absent or expired; reevaluate")
        return dict(
            scenario_id=scenario_id,
            dynamic_vectors=[
                r["dynamic_vector"] for r in result["results"] if r["dynamic_vector"] is not None
            ],
            unevaluated_cell_ids=[
                r["cell_id"] for r in result["results"] if r["dynamic_vector"] is None
            ],
        )


class DelayRequest(Scenario):
    original_cell_id: str = Field(min_length=1)


@router.post("/delay", response_model=contract.DelayResponse, response_model_exclude_unset=True)
def delay(request: DelayRequest):
    if not _gate.acquire(blocking=False):
        raise HTTPException(429, "Scientific analysis capacity reached; retry later")
    try:
        scenario = Scenario.model_validate(request.model_dump(exclude={"original_cell_id"}))
        return engine().delay(scenario, request.original_cell_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown dataset or cell ID") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        _gate.release()


class TerrainRequest(contract.StrictModel):
    dataset_id: str
    cell_id: str
    observer_height_m: float = Field(default=1, ge=0, le=100)
    azimuths_deg: list[float] = Field(min_length=1, max_length=360)


@router.post("/terrain/horizon", response_model=contract.Horizon, response_model_exclude_unset=True)
def terrain_diagnostics(request: TerrainRequest):
    from app.providers import terrain

    d = dataset(request.dataset_id)
    try:
        c = d.cell(request.cell_id)
        if not d.metadata.source.get("original_metadata"):
            raise ValueError("Native V3 terrain required")
        if not _gate.acquire(blocking=False):
            raise HTTPException(429, "Scientific analysis capacity reached")
        try:
            result = terrain.compute_horizon(
                c.cell_id, request.observer_height_m, request.azimuths_deg
            )
            if result["source_provenance"].get("dataset_id") != d.metadata.dataset_id:
                raise ValueError("Terrain dataset mismatch")
            return dict(result, model="TERRAIN_PARTIAL", observer_reference_compatible=False)
        finally:
            _gate.release()
    except (ValueError, terrain.TerrainUnavailable, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Unknown original cell") from exc


class RepresentationFit(contract.StrictModel):
    dataset_id: str
    dimensions: int = Field(default=2, ge=1, le=3)


class RepresentationResponse(contract.StrictModel):
    metadata: dict


class RepresentationSearch(contract.StrictModel):
    dataset_id: str
    model_id: str
    cell_id: str
    space: str = "physical-scales-v1"
    limit: int = Field(default=20, ge=1, le=1000)
    accept_descriptive_similarity: bool = False


def model_root():
    return os.getenv("WISPR_MODEL_DIR", "data/models")


@router.post("/representations/fit", response_model=RepresentationResponse)
def fit_representation(request: RepresentationFit):
    from . import representations as rep

    if not _gate.acquire(blocking=False):
        raise HTTPException(429, "Scientific analysis capacity reached")
    try:
        model = rep.fit(dataset(request.dataset_id), request.dimensions)
        rep.save(model, model_root())
        return {"metadata": model}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        _gate.release()


@router.post("/representations/search", response_model=RepresentationResponse)
def search_representation(request: RepresentationSearch):
    from . import representations as rep

    if not request.accept_descriptive_similarity:
        raise HTTPException(422, "Explicit descriptive similarity acceptance required")
    if not _gate.acquire(blocking=False):
        raise HTTPException(429, "Scientific analysis capacity reached")
    try:
        d = dataset(request.dataset_id)
        model = rep.load(request.model_id, model_root(), d)
        return {"metadata": rep.retrieve(d, model, request.cell_id, request.space, request.limit)}
    except FileNotFoundError as exc:
        raise HTTPException(404, "Representation model unavailable") from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        _gate.release()


class BackendStatus(contract.StrictModel):
    status: str
    authoritative_modules: list[str]
    datasets: list[dict]
    sources: list[dict]
    limitations: list[str]


@router.get("/status", response_model=BackendStatus)
def backend_status():
    from lunar_global.api import store
    from lunar_global.sources import SourceProduct
    from lunar_global.storage import sha256

    records = []
    root = store().root
    for name, raw_file in (
        ("lola", "ldem_4.img"),
        ("lroc", "WAC_GLOBAL_E000N1800_004P.IMG"),
        ("diviner", "global_cumul_avg_cyl_90s80s_002.tab"),
    ):
        folder = root / "source_products" / name
        try:
            source = SourceProduct.model_validate_json((folder / "source.json").read_text())
            source.validate_alignment()
            if sha256(folder / raw_file) != source.source_checksum:
                raise ValueError("Source hash mismatch")
            if name == "lola":
                paths, manifest = store().feature_files(128)
                if not paths or manifest["source"]["source_checksum"] != source.source_checksum:
                    raise ValueError("LOLA snapshot unavailable or incompatible")
            elif name == "diviner":
                from lunar_global.thermal import thermal_context

                if not thermal_context(root, -89, 45, 0)["source"]:
                    raise ValueError("Thermal snapshot unavailable")
            else:
                from lunar_global.imagery import context

                context(root, 0, 0)
            records.append(
                dict(source=name, status="INGESTED_AND_VERIFIED", registration=source.model_dump())
            )
        except FileNotFoundError:
            records.append(dict(source=name, status="SOURCE_UNAVAILABLE"))
        except (ValueError, OSError) as exc:
            records.append(dict(source=name, status="FAILED_VALIDATION", reason=str(exc)))
    records.extend(
        [
            dict(
                source="M3",
                status="REGISTERED_ONLY",
                reason="No verified L2 observation imported; metadata/band guard only",
            ),
            dict(
                source="Moon Trek",
                status="REGISTERED_ONLY",
                reason="WMTS documentation reviewed; no scientific measurements imported",
            ),
            dict(
                source="QuickMap",
                status="REGISTERED_ONLY",
                reason="No validated scientific adapter configured",
            ),
            dict(
                source="JPL SBDB",
                status="NOT_APPLICABLE",
                reason="Small-body database is not lunar Sun/Earth geometry",
            ),
            dict(
                source="JPL Horizons",
                status="ON_DEMAND",
                reason="Existing validated celestial engine; per-response LIVE or VERIFIED_CACHE provenance",
            ),
        ]
    )
    registry = engine().registry
    return dict(
        status="READY"
        if registry.datasets and all(r["status"] == "INGESTED_AND_VERIFIED" for r in records[:3])
        else "DEGRADED",
        authoritative_modules=[
            "app.integration",
            "lunar_global",
            "celestial_engine",
            "app.providers.terrain",
        ],
        datasets=[
            dict(dataset_id=d.metadata.dataset_id, sha256=d.digest, cells=len(d.cells))
            for d in registry.datasets.values()
        ],
        sources=records,
        limitations=[
            "Readiness verifies configured raw-source hashes, not NASA network availability",
            "Terrain physical visibility remains UNKNOWN without verified references and error bounds",
            "Local prototype: no public deployment or authentication",
        ],
    )
