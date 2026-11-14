"""Align source-backed Sun/Earth observations without terrain inference."""

import json
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .cache import atomic_write
from .data_validation import align
from .horizons_client import HorizonsClient
from .schemas import EphemerisResult, Observation

ANGLE_FIELDS = [
    f"{body}_{angle}_deg" for body in ("sun", "earth") for angle in ("azimuth", "elevation")
]
UNITS = {
    **dict.fromkeys(ANGLE_FIELDS + ["latitude_deg", "longitude_east_deg"], "degree"),
    "altitude_km": "km",
    "timestamp_utc": "UTC",
}


class CelestialService:
    def __init__(self, client=None):
        self.client = client or HorizonsClient()

    def ephemeris(self, request):
        sun, sm = self.client.target(10, request)
        earth, em = self.client.target(399, request)
        timestamps, matching = align(sun, earth, request)
        records = []
        for stamp in timestamps:
            s, e = sun.get(stamp), earth.get(stamp)
            valid = s is not None and e is not None
            values = dict(
                zip(
                    ANGLE_FIELDS,
                    (*(s or (None, None)), *(e or (None, None))),
                    strict=True,
                )
            )
            records.append(
                Observation(
                    timestamp_utc=stamp,
                    **values,
                    latitude_deg=request.latitude_deg,
                    longitude_east_deg=request.longitude_east_deg,
                    altitude_km=request.altitude_km,
                    valid=valid,
                    quality="SOURCE_BACKED" if valid else "MISSING_OBSERVATION",
                )
            )
        return EphemerisResult(
            records=records,
            metadata=dict(
                processing_version=__version__,
                generated_at_utc=datetime.now(UTC).isoformat(),
                source="NASA JPL Horizons",
                feature_names=ANGLE_FIELDS,
                units=UNITS,
                request=request.model_dump(mode="json"),
                queries={"sun": sm, "earth": em},
                coordinate_reference="MOON_ME / DE421 mean-Earth frame; Horizons lunar reference surface",
                altitude_reference="horizons_lunar_reference",
                azimuth_convention="clockwise from north, [0,360)",
                elevation_convention="airless apparent target center above local normal plane; degrees",
                time_standard="UTC (Horizons UT for modern dates)",
                target_timestamp_sets_match=matching,
                sample_count=len(records),
                missing_observations=sum(not r.valid for r in records),
                data_quality="SOURCE_BACKED" if all(r.valid for r in records) else "PARTIAL",
                limitations=[
                    "Research prototype, not flight or mission certified",
                    "No terrain obstruction, illumination windows, power or communications link budget calculated",
                    "DEM heights require verified frame and vertical-reference conversion before use",
                    "Quantity 4 is apparent geometry including light-time and aberration, not uncorrected geometric vectors",
                ],
            ),
        )


def export_result(result, directory):
    """Write physical-unit JSON and typed UTC Parquet with identical provenance."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    metadata = json.dumps(result.metadata, indent=2, allow_nan=False).encode()
    atomic_write(directory / "sample_ephemeris.json", result.model_dump_json(indent=2).encode())
    atomic_write(directory / "query_metadata.json", metadata)
    schema = pa.schema(
        [
            pa.field("timestamp_utc", pa.timestamp("us", tz="UTC")),
            *[
                pa.field(name, pa.float64())
                for name in ANGLE_FIELDS + ["latitude_deg", "longitude_east_deg", "altitude_km"]
            ],
            pa.field("source", pa.string()),
            pa.field("valid", pa.bool_()),
            pa.field("quality", pa.string()),
        ],
        metadata={b"wispr_metadata": metadata},
    )
    table = pa.Table.from_pylist([row.model_dump() for row in result.records], schema=schema)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="NONE")
    atomic_write(directory / "sample_ephemeris.parquet", sink.getvalue().to_pybytes())
