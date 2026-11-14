"""Source-bound numerical uncertainty, never inferred from dict truthiness."""

import math

FEATURE_UNITS = {"elevation_m": "m", "slope_deg": "degree", "roughness_m": "m"}


def uncertainty_status(cell, metadata):
    evidence = cell.uncertainty
    if not evidence or all(v is None for v in evidence.values()):
        return "UNCERTAINTY_UNKNOWN"
    if evidence.get("schema") != "measurement-standard-uncertainty-v1":
        return "UNCERTAINTY_UNKNOWN"
    source_id = cell.source.get("source_id") or metadata.source.get("source_id")
    if (
        not source_id
        or evidence.get("source_id") != source_id
        or evidence.get("terrain_definition") != metadata.terrain_definition
        or cell.quality != "VERIFIED"
        or not isinstance(evidence.get("citation"), str)
        or not evidence["citation"].strip()
    ):
        return "INCOMPATIBLE_EVIDENCE"
    values = evidence.get("measurements")
    if not isinstance(values, dict) or set(values) != set(FEATURE_UNITS):
        return "INCOMPATIBLE_EVIDENCE"
    for name, unit in FEATURE_UNITS.items():
        item = values[name]
        if not isinstance(item, dict) or item.get("unit") != unit:
            return "INCOMPATIBLE_EVIDENCE"
        sigma = item.get("standard_uncertainty")
        if type(sigma) not in (int, float) or not math.isfinite(sigma) or sigma < 0:
            return "INCOMPATIBLE_EVIDENCE"
    return "VERIFIED_NUMERICAL_UNCERTAINTY"


def descriptive_source_supported(cell, metadata):
    if cell.quality in ("VERIFIED", "SOURCE_BACKED"):
        return True
    # Frozen V3's declared missing uncertainty is not a failed quality check.
    # Require its independently checked manifest evidence; never relabel it VERIFIED.
    return (
        cell.quality == "source_lola_count_and_uncertainty_not_supplied"
        and bool(metadata.source.get("verified_files"))
        and cell.source.get("raw_dem_sha256")
        == metadata.source.get("original_metadata", {}).get("source", {}).get("sha256")
    )
