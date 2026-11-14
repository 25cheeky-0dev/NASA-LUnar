"""Range and cadence checks; no replacement astronomy calculations."""

import math


class EphemerisError(ValueError):
    """NASA payload cannot be interpreted as the requested observations."""


def angles(azimuth, elevation):
    if not (math.isfinite(azimuth) and 0 <= azimuth < 360):
        raise EphemerisError("Azimuth must be finite and in [0,360) degrees")
    if not (math.isfinite(elevation) and -90 <= elevation <= 90):
        raise EphemerisError("Elevation must be finite and in [-90,90] degrees")


def align(sun, earth, request):
    expected = request.timestamps()
    allowed = set(expected)
    if (set(sun) | set(earth)) - allowed:
        raise EphemerisError("NASA returned timestamps outside the requested cadence")
    return expected, set(sun) == set(earth)
