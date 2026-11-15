"""Moon-centered geometry shared by the terrain provider and V3 horizon engine."""

import numpy as np


def elevation_angle(distance_m, observer_radius_m, terrain_radius_m, reference_radius_m):
    """Exact radial-up elevation on a sphere; distance is reference-sphere arc length.

    The half-angle form avoids subtracting nearly equal Moon-sized coordinates.
    Both radii are absolute distances from the Moon center, not height differences.
    """
    theta = np.asarray(distance_m, dtype=float) / reference_radius_m
    radial = terrain_radius_m - observer_radius_m - 2 * terrain_radius_m * np.sin(theta / 2) ** 2
    horizontal = terrain_radius_m * np.sin(theta)
    return np.degrees(np.arctan2(radial, horizontal))
