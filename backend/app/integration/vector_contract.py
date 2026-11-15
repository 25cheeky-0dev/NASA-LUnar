"""Shared physical feature order and fixed scales for global and native cells."""

FEATURES = ["elevation_m", "slope_deg", "roughness_m"]
UNITS = dict(zip(FEATURES, ["m", "degree", "m"]))
# Fixed physical scales, not a safety score or dataset-dependent fitted statistics.
NORMALIZATION = dict(
    version="physical-scales-v1",
    strategy="x / scale; no clipping or imputation",
    offsets=[0.0, 0.0, 0.0],
    scales=[1000.0, 10.0, 10.0],
    units=UNITS,
)
