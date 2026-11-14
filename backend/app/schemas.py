from datetime import datetime, timedelta, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SiteID = Literal['R01', 'R04']
Model = Literal['GEOMETRIC', 'LOCAL_TERRAIN']


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset().total_seconds() != 0:
        raise ValueError('Explicit UTC with Z or +00:00 is required')
    if value.second or value.microsecond:
        raise ValueError('Use whole UTC minutes for Horizons sampling')
    if not 1900 <= value.year <= 2100:
        raise ValueError('Supported years: 1900–2100')
    return value.astimezone(timezone.utc)


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class RecoveryRequest(Strict):
    original_site_id: SiteID | None = None
    original_arrival_utc: datetime | None = None
    study_duration_hours: float | None = Field(None, gt=0, le=48)
    delay_hours: Literal[168] = 168
    min_continuous_overlap_minutes: float = Field(180, gt=0, le=2880)
    candidate_site_ids: list[SiteID] = Field(default_factory=lambda: ['R01', 'R04'])
    horizon_model: Model = 'GEOMETRIC'
    observer_height_m: float = Field(1, ge=0, le=100)
    step_minutes: int = Field(5, ge=1, le=60)
    future_search_days: int = Field(0, ge=0, le=7)

    @field_validator('original_arrival_utc')
    @classmethod
    def check_utc(cls, value):
        return utc(value) if value else None

    @field_validator('candidate_site_ids')
    @classmethod
    def both_sites(cls, value):
        if set(value) != {'R01', 'R04'} or len(value) != 2:
            raise ValueError('V1 compares exactly R01 and R04')
        return ['R01', 'R04']

    @model_validator(mode='after')
    def whole_minutes(self):
        if self.study_duration_hours and abs(self.study_duration_hours * 60 - round(self.study_duration_hours * 60)) > 1e-8:
            raise ValueError('Study duration must be a whole number of minutes')
        if self.original_arrival_utc and self.study_duration_hours:
            latest_end = self.original_arrival_utc + timedelta(
                hours=self.delay_hours + self.study_duration_hours, days=self.future_search_days)
            if latest_end.year > 2100:
                raise ValueError('The delayed study and future search must end within 1900–2100')
        return self


class EphemerisRequest(Strict):
    site_id: str | None = None
    lat_deg: float | None = Field(None, ge=-90, le=90)
    lon_east_deg: float | None = Field(None, ge=0, lt=360)
    start_utc: datetime
    end_utc: datetime
    step_minutes: int = Field(5, ge=1, le=60)
    observer_height_m: float = Field(1, ge=0, le=100)
    source_preference: Literal['LIVE_THEN_VERIFIED_CACHE', 'VERIFIED_CACHE_ONLY'] = 'LIVE_THEN_VERIFIED_CACHE'

    @field_validator('start_utc', 'end_utc')
    @classmethod
    def dates(cls, value):
        return utc(value)

    @model_validator(mode='after')
    def valid(self):
        if self.site_id is not None:
            if self.lat_deg is not None or self.lon_east_deg is not None:
                raise ValueError('Use site_id OR coordinates')
        elif self.lat_deg is None or self.lon_east_deg is None:
            raise ValueError('Provide site_id or both coordinates')
        if not 0 < (self.end_utc - self.start_utc).total_seconds() <= 48 * 3600:
            raise ValueError('Interval must be positive and at most 48h')
        return self


class AnalyzeRequest(Strict):
    site_ids: list[SiteID] = Field(min_length=1, max_length=2)
    start_utc: datetime
    end_utc: datetime
    min_continuous_overlap_minutes: float = Field(180, gt=0, le=2880)
    horizon_model: Model = 'GEOMETRIC'
    observer_height_m: float = Field(1, ge=0, le=100)
    step_minutes: int = Field(5, ge=1, le=60)

    @field_validator('start_utc', 'end_utc')
    @classmethod
    def dates(cls, value):
        return utc(value)

    @model_validator(mode='after')
    def valid(self):
        if not 0 < (self.end_utc - self.start_utc).total_seconds() <= 48 * 3600:
            raise ValueError('Interval must be positive and at most 48h')
        if len(set(self.site_ids)) != len(self.site_ids):
            raise ValueError('Duplicate sites')
        return self


class SkyPosition(Strict):
    az_deg: float | None = None
    el_deg: float | None = None
    east: float | None = None
    north: float | None = None
    up: float | None = None
    status: Literal['KNOWN', 'UNKNOWN']


class SyncedRecord(Strict):
    timestamp_utc: str
    sun: SkyPosition | None
    earth: SkyPosition | None
    status: Literal['KNOWN', 'UNKNOWN']
    gap_reason: str | None = None


class VisibilityWindow(Strict):
    start_utc: str
    end_utc: str
    duration_minutes: float
    kind: Literal['SUN', 'EARTH', 'BOTH']
    estimate_status: Literal['MODEL_ESTIMATE', 'BRACKETED', 'UNKNOWN'] = 'MODEL_ESTIMATE'
    boundary_uncertainty_seconds: float
    model: str = 'GEOMETRIC_IDEAL'


class ScenarioSummary(BaseModel):
    model_config = ConfigDict(extra='allow')
    scenario_id: str
    site_id: str
    arrival_utc: str
    end_utc: str
    horizon_model: Model
    sun_windows: list[VisibilityWindow]
    earth_windows: list[VisibilityWindow]
    shared_windows: list[VisibilityWindow]
    longest_shared_minutes: float | None
    earliest_qualifying_window: VisibilityWindow | None
    known_fraction: float
    unknown_fraction: float
    qualifying_status: Literal['QUALIFIES', 'FAILS', 'UNKNOWN']
    reason_codes: list[str]
    visibility_series: list[SyncedRecord]
    provenance: dict
    limitations: list[str]


class RecoveryResponse(BaseModel):
    model_config = ConfigDict(extra='allow')
    request: dict
    search_scope: dict
    original_scenarios: list[ScenarioSummary]
    delayed_scenarios: list[ScenarioSummary]
    ranked_eligible: list[ScenarioSummary]
    recommended_outcome: Literal['KEEP_SITE_AFTER_DELAY', 'SWITCH_SITE_AFTER_DELAY', 'POSTPONE_AND_REEVALUATE', 'NO_QUALIFYING_OPTION_WITHIN_SEARCH', 'INSUFFICIENT_DATA', 'NEEDS_INPUT']
    recommended_site_id: str | None
    recommended_window: VisibilityWindow | None


class ScientificResponse(BaseModel):
    model_config = ConfigDict(extra='allow')
    api_version: str
    backend_version: str
    computed_at_utc: str
    source_type: str
    calculation_mode: str
    data_quality: str
    limitations: list[str]
    provenance: dict


class Site(BaseModel):
    model_config = ConfigDict(extra='allow')
    site_id: SiteID
    name: str
    lat_deg: float
    lon_east_deg: float
    reference_region_not_certified_site: bool
    dem_site_id: str
    dem_status: str


class SitesResponse(ScientificResponse):
    sites: list[Site]


class Cell(BaseModel):
    cell_id: str
    grid_version: str
    cell_size_m: int
    center_lat_deg: float
    center_lon_east_deg: float
    center_x_m: float
    center_y_m: float
    boundary_lonlat_east: list[list[float]]
    raster_coverage: str
    ephemeris_status: str
    observations_represent_center_only: bool


class GridResponse(ScientificResponse):
    site_id: SiteID
    grid_version: str
    projection: dict
    cells: list[Cell]
    center_cell_id: str


class EphemerisResponse(ScientificResponse):
    site: dict
    records: list[SyncedRecord]
    observed_start_utc: str
    observed_end_utc: str
    missing_intervals: list[dict]
    step_minutes: int


class AnalyzeResponse(ScientificResponse):
    scenarios: list[ScenarioSummary]


class PhysicalFeatures(BaseModel):
    model_config = ConfigDict(extra='allow')
    cell_id: str
    scenario_id: str
    feature_names: list[str]
    values: list[float | None]
    normalized_values: list[float] | None
    normalization_version: str
    available_features: list[str]
    missing_features: list[str]
    similarity_eligible: bool
    quality: str


class FeaturesResponse(ScientificResponse):
    scenario_id: str
    feature_definitions: list[dict]
    points: list[PhysicalFeatures]
    reference_points: list[PhysicalFeatures]
    scatter_axes: dict
    normalization: dict
    ignored_or_missing: list[dict]
