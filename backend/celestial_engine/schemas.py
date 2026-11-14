"""Strict scientific request and response contracts."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class EphemerisRequest(StrictModel):
    latitude_deg: float = Field(ge=-90, le=90)
    longitude_east_deg: float = Field(ge=0, lt=360)
    altitude_km: float = Field(default=0, ge=-10, le=100)
    altitude_reference: Literal["horizons_lunar_reference"] = "horizons_lunar_reference"
    start_utc: datetime
    end_utc: datetime
    step_minutes: int = Field(default=60, ge=1, le=1440, strict=True)

    @field_validator("start_utc", "end_utc")
    @classmethod
    def utc_minute(cls, value):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("Explicit UTC (Z or +00:00) required")
        if value.second or value.microsecond:
            raise ValueError("Whole UTC minutes required")
        if not 1900 <= value.year <= 2100:
            raise ValueError("Research service supports years 1900–2100")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def interval(self):
        minutes = (self.end_utc - self.start_utc).total_seconds() / 60
        if not 0 < minutes <= 31 * 1440:
            raise ValueError("Interval must be positive and at most 31 days")
        if minutes % self.step_minutes:
            raise ValueError("Interval must contain an integer number of steps")
        if minutes / self.step_minutes + 1 > 10000:
            raise ValueError("At most 10000 inclusive samples per request")
        return self

    def timestamps(self):
        count = int((self.end_utc - self.start_utc).total_seconds() / (60 * self.step_minutes))
        return [self.start_utc + timedelta(minutes=i * self.step_minutes) for i in range(count + 1)]


class Observation(StrictModel):
    timestamp_utc: datetime
    sun_azimuth_deg: float | None
    sun_elevation_deg: float | None
    earth_azimuth_deg: float | None
    earth_elevation_deg: float | None
    latitude_deg: float
    longitude_east_deg: float
    altitude_km: float
    source: Literal["NASA_JPL_HORIZONS"] = "NASA_JPL_HORIZONS"
    valid: bool
    quality: Literal["SOURCE_BACKED", "MISSING_OBSERVATION"]


class EphemerisResult(StrictModel):
    records: list[Observation]
    metadata: dict
