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
def similarity(dataset_id: str, cell_id: str, limit: int = Query(20, ge=1, le=1000)):
    try:
        return dataset(dataset_id).similarity(cell_id, limit)
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
