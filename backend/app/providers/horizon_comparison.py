"""Additive adapter for unchanged CelestialService EphemerisResult objects."""

import copy
import hashlib
import math
from datetime import datetime

from celestial_engine.ephemeris_parser import parse_response
from celestial_engine.schemas import EphemerisRequest

from .terrain_horizon import AZIMUTH_CONVENTION, classify_visibility


def compare_ephemeris(engine, cell_id, observer_height_m, ephemeris, *, raw_sources=None):
    """Preserve NASA rows verbatim and calculate their actual Sun/Earth directions.

    For certification, supply original NASA response bytes for both targets.
    They are hashed and revalidated with the existing Celestial Engine parser.
    Missing references or hard terrain-error bounds leave decisions UNKNOWN.
    No angular interpolation and no ephemeris resampling occur here.
    """
    source = (
        ephemeris.model_dump(mode="json")
        if hasattr(ephemeris, "model_dump")
        else copy.deepcopy(ephemeris)
    )
    records, meta = source["records"], source["metadata"]
    azimuths = [
        r[f"{b}_azimuth_deg"]
        for r in records
        for b in ("sun", "earth")
        if r.get(f"{b}_azimuth_deg") is not None and math.isfinite(r[f"{b}_azimuth_deg"])
    ]
    # Even missing observations retain observer/source diagnostics.
    horizon = engine.compute_horizon(
        cell_id, observer_height_m, list(dict.fromkeys(azimuths)) or [0]
    )
    rays = {r["azimuth_deg"]: r for r in horizon["azimuth_samples"]}
    position = horizon["observation_position"]
    failures = []
    if not horizon["vertical_reference_verified"]:
        failures.append("DEM_VERTICAL_REFERENCE_UNVERIFIED")
    if engine.references.frame != "MOON_ME_DE421" or engine.references.radius_m != 1737400:
        failures.append("LUNAR_FRAME_OR_RADIUS_INCOMPATIBLE")
    if meta.get("azimuth_convention") != AZIMUTH_CONVENTION:
        failures.append("AZIMUTH_CONVENTION_UNVERIFIED")
    if meta.get("altitude_reference") != "horizons_lunar_reference":
        failures.append("HORIZONS_ALTITUDE_REFERENCE_UNVERIFIED")
    request = None
    parsed = {}
    try:
        request = EphemerisRequest.model_validate(
            {k: v for k, v in meta["request"].items() if k in EphemerisRequest.model_fields}
        )
        if (
            abs(request.latitude_deg - position["latitude_deg"]) > 1e-10
            or abs((request.longitude_east_deg - position["longitude_east_deg"] + 180) % 360 - 180)
            > 1e-10
            or abs(request.altitude_km * 1000 - (horizon["observer_radius_m"] - 1737400)) > 1e-6
        ):
            failures.append("OBSERVER_POSITION_OR_ALTITUDE_MISMATCH")
        for body, target in (("sun", 10), ("earth", 399)):
            raw = (raw_sources or {}).get(body)
            if raw is None:
                failures.append(f"{body.upper()}_RAW_SOURCE_NOT_REVALIDATED")
                continue
            if hashlib.sha256(raw).hexdigest() != meta["queries"][body]["raw_sha256"]:
                raise ValueError("Raw source checksum mismatch")
            parsed[body] = parse_response(raw, target, request)
    except (ValueError, KeyError, TypeError) as exc:
        failures.append(f"SOURCE_REFERENCE_VALIDATION_FAILED: {exc}")
    joined = []
    for record in records:
        row_failures = list(failures)
        if request is not None and (
            record.get("latitude_deg") != request.latitude_deg
            or record.get("longitude_east_deg") != request.longitude_east_deg
            or record.get("altitude_km") != request.altitude_km
        ):
            row_failures.append("ROW_OBSERVER_MISMATCH")
        row = dict(source_observation=copy.deepcopy(record), terrain={})
        for body in ("sun", "earth"):
            az, el = record.get(f"{body}_azimuth_deg"), record.get(f"{body}_elevation_deg")
            body_failures = list(row_failures)
            if body in parsed:
                try:
                    stamp = datetime.fromisoformat(record["timestamp_utc"].replace("Z", "+00:00"))
                    if parsed[body].get(stamp) != (az, el):
                        body_failures.append("ROW_DIFFERS_FROM_NASA_SOURCE")
                except (ValueError, TypeError, KeyError):
                    body_failures.append("INVALID_SOURCE_TIMESTAMP")
            ray = rays.get(az % 360) if az is not None and math.isfinite(az) else None
            compatible = not body_failures
            if ray and ray["verified_obstruction_lower_bound_deg"] is None:
                body_failures.append("TERRAIN_ERROR_BOUND_UNRESOLVED")
            state = classify_visibility(ray, el, reference_compatible=compatible)
            row["terrain"][body] = dict(
                state=state,
                observer_reference_compatible=compatible,
                reasons=body_failures,
                ray=copy.deepcopy(ray),
                target_treatment="CENTER_ONLY",
            )
        joined.append(row)
    return dict(
        cell_id=cell_id,
        model="TERRAIN_PARTIAL",
        far_field_complete=False,
        records=joined,
        original_metadata=copy.deepcopy(meta),
        horizon=horizon,
        compatibility_failures=failures,
        target_treatment="CENTER_ONLY",
    )
