"""Additive router; existing WISPR endpoint contracts remain compatible."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .celestial_service import CelestialService
from .data_validation import EphemerisError
from .horizons_client import SourceUnavailable
from .schemas import EphemerisRequest, EphemerisResult

router = APIRouter(prefix="/api/v1/celestial", tags=["celestial"])
service = CelestialService()


def get_service():
    return service


@router.get("/health")
def health():
    return dict(
        status="OK",
        engine_version="1.0.0",
        horizons_status="NOT_PROBED",
        mode="AIRLESS_APPARENT_GEOMETRY",
        terrain_obstruction="NOT_CALCULATED",
    )


@router.post(
    "/ephemeris",
    response_model=EphemerisResult,
    responses={503: {"description": "NASA unavailable or response failed scientific validation"}},
)
def ephemeris(request: EphemerisRequest, engine: CelestialService = Depends(get_service)):
    try:
        return engine.ephemeris(request)
    except (SourceUnavailable, EphemerisError) as exc:
        return JSONResponse(
            status_code=503,
            content=dict(error_code="SOURCE_UNAVAILABLE", detail=str(exc), fallback="NONE"),
        )
    except OSError:
        return JSONResponse(
            status_code=503,
            content=dict(
                error_code="CACHE_UNAVAILABLE",
                detail="Local cache storage unavailable",
                fallback="NONE",
            ),
        )
