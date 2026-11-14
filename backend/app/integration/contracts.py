"""Published science response contract. Source-specific dictionaries stay lossless."""

from typing import Literal

from pydantic import Field

from celestial_engine.schemas import StrictModel

from .engine import Scenario
from .grid import Cell, Filters, Metadata

PhysicalVector = tuple[float | None, float | None, float | None]


class ErrorDetail(StrictModel):
    loc: list[str | int]
    msg: str


class ScienceError(StrictModel):
    error_code: str
    detail: str | list[ErrorDetail]
    missing_fields: list[str]


class DatasetInfo(Metadata):
    cell_count: int
    sha256: str


class IngestionError(StrictModel):
    file: str
    error: str


class DatasetPage(StrictModel):
    datasets: list[DatasetInfo]
    total: int
    offset: int
    limit: int
    ingestion_errors: list[IngestionError]
    status: Literal["AVAILABLE", "MISSING_GRID_ASSETS"]


class CellPage(StrictModel):
    cells: list[Cell]
    total: int
    offset: int
    limit: int


class CellResponse(StrictModel):
    cell: Cell
    metadata: Metadata
    dataset_sha256: str


class TerrainEvidence(StrictModel):
    resolution_m: float | None
    terrain_definition: str
    elevation_datum: str
    coordinate_frame: str
    quality: str
    uncertainty: dict
    coverage_fraction: float | None
    synthetic: bool


class Normalization(StrictModel):
    version: Literal["physical-scales-v1"]
    strategy: str
    offsets: tuple[float, float, float]
    scales: tuple[float, float, float]
    units: dict[str, str]


class StaticProvenance(StrictModel):
    dataset_sha256: str
    dataset_source: dict
    cell_source: dict


class StaticVector(StrictModel):
    cell_id: str
    grid_version: str
    dataset_id: str
    feature_names: tuple[Literal["elevation_m"], Literal["slope_deg"], Literal["roughness_m"]]
    units: dict[str, str]
    raw: PhysicalVector
    normalized: PhysicalVector
    missing_mask: tuple[bool, bool, bool]
    normalization: Normalization
    quality: TerrainEvidence
    valid: bool
    provenance: StaticProvenance


class SimilarityMatch(StrictModel):
    cell_id: str
    normalized_euclidean_distance: float


class SimilarityResponse(StrictModel):
    reference_cell_id: str
    metric: str
    comparability: TerrainEvidence
    matches: list[SimilarityMatch]


class CandidateResponse(StrictModel):
    cell_ids: list[str]
    total: int
    offset: int
    limit: int
    filters: Filters
    units: dict[str, str]
    ordering: str


class VisibilityWindow(StrictModel):
    start_utc: str
    end_utc: str
    duration_minutes: float
    kind: Literal["SUN", "EARTH", "BOTH"]
    estimate_status: Literal["MODEL_ESTIMATE"]
    boundary_uncertainty_seconds: int
    model: Literal["GEOMETRIC_IDEAL", "TERRAIN_PARTIAL"]


class UnknownInterval(StrictModel):
    start_utc: str
    end_utc: str
    reason: str


class Crossing(StrictModel):
    timestamp_utc: str | None
    reason: str | None
    boundary_uncertainty_seconds: int


class VisibilityMetrics(StrictModel):
    sun_visible_fraction: float | None
    earth_visible_fraction: float | None
    both_visible_fraction: float | None


class WindowSummary(StrictModel):
    sun_windows: list[VisibilityWindow]
    earth_windows: list[VisibilityWindow]
    shared_windows: list[VisibilityWindow]
    longest_shared_minutes: float | None
    earliest_qualifying_window: VisibilityWindow | None
    known_fraction: float
    unknown_fraction: float
    qualifying_status: Literal["QUALIFIES", "UNKNOWN", "FAILS"]
    reason_codes: list[str]
    unknown_intervals: list[UnknownInterval]
    next_crossings: dict[str, Crossing]
    metrics: VisibilityMetrics


class DynamicFeatures(StrictModel):
    sun_modeled_visibility_fraction: float | None
    earth_modeled_visibility_fraction: float | None
    shared_modeled_visibility_fraction: float | None
    longest_shared_minutes: float | None
    earliest_qualifying_shared_window: VisibilityWindow | None
    unknown_data_fraction: float
    summary: WindowSummary
    fraction_definition: str
    window_model: str
    terrain_clearance_supported: bool


class VisibilityState(StrictModel):
    state: Literal[
        "UNKNOWN",
        "GEOMETRIC_VISIBLE",
        "GEOMETRIC_HIDDEN",
        "UNKNOWN_OBSERVER_REFERENCE",
        "TERRAIN_OBSTRUCTED",
        "INCOMPLETE_HORIZON_COVERAGE",
    ]
    geometric_visible: bool | None
    modeled_visible: bool | None
    clearance_deg: float | None


class JoinedObservation(StrictModel):
    cell_id: str
    timestamp_utc: str
    sun_azimuth_deg: float | None
    sun_elevation_deg: float | None
    earth_azimuth_deg: float | None
    earth_elevation_deg: float | None
    sun: VisibilityState
    earth: VisibilityState


class Observer(StrictModel):
    latitude_deg: float
    longitude_east_deg: float
    altitude_km: float
    altitude_reference: Literal["horizons_lunar_reference"]
    start_utc: str
    end_utc: str
    step_minutes: int


class SkylineSample(StrictModel):
    azimuth_deg: float
    terrain_horizon_elevation_deg: float | None
    coverage: str
    uncertainty_deg: float | None
    supported_radius_m: float


class Horizon(StrictModel):
    # Provider-specific scientific metadata is intentionally extensible.
    model_config = {"extra": "allow", "allow_inf_nan": False}
    model: Literal["GEOMETRIC_IDEAL", "TERRAIN_PARTIAL"]
    far_field_complete: bool | None = None
    limitations: list[str] | None = None
    coverage: str | None = None
    observer_reference_compatible: bool | None = None
    azimuth_samples: list[SkylineSample] | None = None
    max_supported_radius_m: float | None = None
    observer_ground_height_m: float | None = None
    observer_height_m: float | None = None
    observation_position: dict[str, float] | None = None
    source_manifest: dict | None = None
    raster_sha256: str | None = None


class QueryProvenance(StrictModel):
    model_config = {"extra": "allow", "allow_inf_nan": False}
    query_parameters: dict[str, str]
    source_url: str
    raw_sha256: str
    retrieved_at_utc: str
    parser_version: str
    api_signature: dict
    ephemeris_header: str
    delivery: Literal["LIVE", "VERIFIED_CACHE"]


class CelestialProvenance(StrictModel):
    model_config = {"extra": "allow", "allow_inf_nan": False}
    source: str
    processing_version: str | None = None
    generated_at_utc: str | None = None
    feature_names: list[str] | None = None
    units: dict[str, str] | None = None
    request: Observer | None = None
    queries: dict[str, QueryProvenance] | None = None
    coordinate_reference: str | None = None
    altitude_reference: str | None = None
    azimuth_convention: str | None = None
    elevation_convention: str | None = None
    time_standard: str | None = None
    target_timestamp_sets_match: bool | None = None
    sample_count: int | None = None
    missing_observations: int | None = None
    data_quality: str | None = None
    limitations: list[str] | None = None


class DynamicVector(StrictModel):
    cell_id: str
    grid_version: str
    dataset_id: str
    start_utc: str
    end_utc: str
    observer: Observer
    observer_height_m: float
    horizon_model: Literal["GEOMETRIC_IDEAL", "TERRAIN_PARTIAL"]
    horizon: Horizon
    sampling_cadence_minutes: int
    provenance: CelestialProvenance
    features: DynamicFeatures
    quality: Literal["COMPLETE_MODELED_INTERVAL", "INCOMPLETE"]
    missing_data: bool
    units: dict[str, str]
    records: list[JoinedObservation]


class CombinedCell(StrictModel):
    cell_id: str
    dataset_id: str
    grid_version: str
    cell: Cell
    static_vector: StaticVector
    engineering_constraint_failures: list[str]
    status: Literal["NOT_EVALUATED", "UNKNOWN", "EVALUATED"]
    dynamic_vector: DynamicVector | None
    reasons: list[str] = Field(default_factory=list)


class RankedCell(StrictModel):
    cell_id: str
    longest_shared_minutes: float
    static_measurements: PhysicalVector
    terrain_evidence: TerrainEvidence


class ExcludedCell(StrictModel):
    cell_id: str
    reasons: list[str]


class Comparison(StrictModel):
    ranked: list[RankedCell]
    excluded: list[ExcludedCell]
    temporal_resolution_minutes: int
    significance_warning: str
    criterion: str
    horizon_model: Literal["GEOMETRIC_IDEAL", "TERRAIN_PARTIAL"]
    minimum_shared_minutes: float
    explanation: str


class CombinedResponse(StrictModel):
    dataset: Metadata
    dataset_sha256: str
    scenario: Scenario
    results: list[CombinedCell]
    comparison: Comparison
    scope: str


class AnalysisResponse(CombinedResponse):
    scenario_id: str


class RankingResponse(StrictModel):
    scenario_id: str
    comparison: Comparison
    results: list[CombinedCell]
    scope: str


class ScenarioResponse(StrictModel):
    scenario_id: str
    dynamic_vectors: list[DynamicVector]
    unevaluated_cell_ids: list[str]


class DelayResponse(StrictModel):
    outcome: Literal["KEEP", "SWITCH", "NO QUALIFYING MODELED OPTION", "INSUFFICIENT DATA"]
    selected: RankedCell | None
    reason: str
    original_cell_id: str
    delay_days: Literal[7]
    original: CombinedResponse
    delayed: CombinedResponse
    original_qualifying_ids: list[str]
    limitations: list[str]
