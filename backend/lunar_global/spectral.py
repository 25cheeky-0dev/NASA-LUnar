"""Optional M3 registration boundary; no unverified observation is fabricated."""

import math

from .sources import SourceProduct

STATUS = dict(
    status="UNAVAILABLE",
    dataset_id="CH1-ORB-L-M3-4-L2-REFLECTANCE-V1.0",
    reason="No geolocated L2 observation and associated quality/label files ingested",
    canonical_url="https://pds.nasa.gov/ds-view/pds/viewProfile.jsp?dsid=CH1-ORB-L-M3-4-L2-REFLECTANCE-V1.0",
    required=[
        "RFL.IMG",
        "L2.LBL",
        "RFL.HDR",
        "pixel geolocation",
        "channel quality",
        "acquisition metadata",
    ],
    supported_indices=[],
    mineral_abundance_supported=False,
)


def validate_reflectance_registration(source: SourceProduct, wavelengths_nm, values, quality_flags):
    source.validate_alignment()
    if (
        source.instrument != "M3"
        or source.product_type != "spectral"
        or source.units != "dimensionless reflectance"
    ):
        raise ValueError("M3 calibrated reflectance source required")
    if (
        not wavelengths_nm
        or len(wavelengths_nm) != len(values)
        or len(values) != len(quality_flags)
    ):
        raise ValueError("Missing spectral bands or quality flags")
    if any(not math.isfinite(w) or w <= 0 for w in wavelengths_nm) or sorted(
        set(wavelengths_nm)
    ) != list(wavelengths_nm):
        raise ValueError("Wavelengths must be finite, ordered and unique")
    if any(v is not None and not math.isfinite(v) for v in values):
        raise ValueError("Nonfinite reflectance")
    if not source.temporal_coverage or not source.footprint:
        raise ValueError("Observation time and footprint required")
    return dict(
        source_id=source.source_id,
        wavelengths_nm=wavelengths_nm,
        reflectance=values,
        quality_flags=quality_flags,
        indices={},
        mineral_abundance=None,
    )
