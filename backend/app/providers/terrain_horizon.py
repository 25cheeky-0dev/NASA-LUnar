"""On-demand, conservative terrain horizons over an immutable source DEM snapshot.

V3 IDs/coordinates are read by the existing V3 reader. No grid is regenerated.
Unverified vertical references permit conditional diagnostics, never visibility.
"""

import copy
import hashlib
import json
import math
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS, Geod, Transformer

from .horizon_geometry import elevation_angle
from .terrain import TerrainUnavailable

ALGORITHM_VERSION = "terrain-horizon-1.0.0"
AZIMUTH_CONVENTION = "clockwise from north, [0,360)"


@dataclass(frozen=True)
class ReferenceSettings:
    radius_m: float = 1737400.0
    frame: str = "MOON_ME_DE421"
    # This is an explicit diagnostic hypothesis until independently documented.
    height_interpretation: str = "radial_height_above_reference_sphere"
    vertical_reference_verified: bool = False
    vertical_reference_evidence: str = ""
    height_offset_m: float = 0.0
    # A hard bound, NOT RMS and NOT pixel spacing. None means unresolved.
    elevation_error_bound_m: float | None = None
    error_bound_evidence: str = ""

    def __post_init__(self):
        if not math.isfinite(self.radius_m) or self.radius_m <= 0:
            raise ValueError("Invalid lunar reference radius")
        if not math.isfinite(self.height_offset_m):
            raise ValueError("Invalid height offset")
        if self.height_interpretation != "radial_height_above_reference_sphere":
            raise ValueError("Unsupported height conversion; supply a validated implementation")
        if self.vertical_reference_verified and not self.vertical_reference_evidence.strip():
            raise ValueError("Verified vertical reference requires independent evidence")
        if self.elevation_error_bound_m is not None and (
            not math.isfinite(self.elevation_error_bound_m)
            or self.elevation_error_bound_m < 0
            or not self.error_bound_evidence.strip()
        ):
            raise ValueError("A finite nonnegative hard error bound requires evidence")


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class TerrainHorizonEngine:
    """Load one full DEM, then compute only explicitly requested cells/directions.

    Cached results belong to this immutable in-memory snapshot. Reopen after a
    source change; no persistent cache survives unverified source replacement.
    """

    def __init__(
        self,
        raster_path,
        cells,
        expected_sha256,
        *,
        provenance=None,
        references=None,
        sample_step_m=None,
        cache_size=128,
    ):
        self.references = references or ReferenceSettings()
        self.source_path = Path(raster_path)
        digest = file_sha256(self.source_path)
        if digest != expected_sha256:
            raise TerrainUnavailable("Raster SHA-256 differs from source manifest")
        self.digest = digest
        self.provenance = copy.deepcopy(provenance or {})
        self.provenance.update(
            raw_sha256=digest, checksum_verified=True, source_filename=self.source_path.name
        )
        self.cells = copy.deepcopy(cells)
        self._cache = OrderedDict()
        self._cache_lock = threading.RLock()
        if not isinstance(cache_size, int) or cache_size < 0:
            raise ValueError("cache_size must be a nonnegative integer")
        self.cache_size = cache_size
        with rasterio.open(self.source_path) as raster:
            self.crs = CRS.from_user_input(raster.crs)
            shape = self.crs.ellipsoid
            if (
                not self.crs.is_projected
                or shape.inverse_flattening != 0
                or abs(shape.semi_major_metre - self.references.radius_m) > 1e-6
                or any(a.unit_conversion_factor != 1 for a in self.crs.axis_info)
            ):
                raise TerrainUnavailable("Require a projected metre-based declared lunar sphere")
            if raster.count != 1 or raster.scales != (1.0,) or raster.offsets != (0.0,):
                raise TerrainUnavailable("Require a single unscaled height band in metres")
            self.transform = raster.transform
            self.inverse = ~raster.transform
            self.bounds = tuple(raster.bounds)
            self.resolution = tuple(raster.res)
            source = raster.read(1, masked=True).astype(np.float64)
            self.data = source.filled(np.nan)
            self.data[~np.isfinite(self.data)] = np.nan
            self.data.flags.writeable = False
            self.height, self.width = self.data.shape
            finite = self.data[np.isfinite(self.data)]
            if not finite.size:
                raise TerrainUnavailable("Source DEM contains no valid heights")
            self.raster_metadata = dict(
                width=self.width,
                height=self.height,
                crs_wkt=self.crs.to_wkt(),
                affine=list(self.transform)[:6],
                bounds_m=list(self.bounds),
                pixel_size_m=list(self.resolution),
                dtype=raster.dtypes[0],
                nodata=str(raster.nodata),
                valid_pixels=int(finite.size),
                invalid_pixels=int(self.data.size - finite.size),
                elevation_min_m=float(finite.min()),
                elevation_max_m=float(finite.max()),
                elevation_mean_m=float(finite.mean()),
            )
        self.forward = Transformer.from_crs(self.crs.geodetic_crs, self.crs, always_xy=True)
        self.reverse = Transformer.from_crs(self.crs, self.crs.geodetic_crs, always_xy=True)
        self.geod = Geod(a=self.references.radius_m, b=self.references.radius_m)
        self.sample_step_m = float(
            min(self.resolution) / 2 if sample_step_m is None else sample_step_m
        )
        if (
            not math.isfinite(self.sample_step_m)
            or self.sample_step_m <= 0
            or self.sample_step_m > min(self.resolution) / 2
        ):
            raise ValueError("Ray spacing must be positive and at most half a native pixel")
        if self.references.radius_m + float(finite.min()) + self.references.height_offset_m <= 0:
            raise TerrainUnavailable("Height interpretation gives a nonpositive lunar radius")

    @classmethod
    def from_v3(cls, root, **kwargs):
        from app.integration.v3 import read_v3

        root = Path(root)
        dataset = read_v3(root)  # Existing checksum/ID/coordinate validation, no rebuild.
        baseline = dataset.metadata.source["original_metadata"]
        cells = {
            c.cell_id: dict(
                latitude_deg=c.latitude_deg,
                longitude_east_deg=dataset.east_longitude(c),
                x_m=c.projected_x,
                y_m=c.projected_y,
            )
            for c in dataset.cells
        }
        engine = cls(
            root / baseline["source"]["filename"],
            cells,
            baseline["source"]["sha256"],
            provenance=dict(
                source_url=baseline["source"]["url"],
                source_vertical_reference=baseline["crs"]["vertical_reference"],
                source_frame=baseline["crs"]["frame"],
                package_manifest_sha256=file_sha256(root / "SHA256_MANIFEST.json"),
                verified_files=dataset.metadata.source["verified_files"],
                dataset_id=dataset.metadata.dataset_id,
            ),
            **kwargs,
        )
        if (
            (engine.width, engine.height) != (3200, 3200)
            or engine.resolution != (5.0, 5.0)
            or list(engine.transform)[:6] != baseline["source"]["source_affine"]
            or not engine.crs.equals(CRS.from_wkt(baseline["crs"]["wkt"]))
        ):
            raise TerrainUnavailable("Native Site04 raster does not match frozen V3 metadata")
        return engine

    def _sample(self, xs, ys):
        """Bilinear source-pixel centers; all four supporting pixels must be valid.

        No extrapolation, masked-hole bridging, or nearest-valid substitution.
        """
        xs, ys = np.broadcast_arrays(np.asarray(xs, float), np.asarray(ys, float))
        col = self.inverse.a * xs + self.inverse.b * ys + self.inverse.c - 0.5
        row = self.inverse.d * xs + self.inverse.e * ys + self.inverse.f - 0.5
        inside = (
            np.isfinite(col)
            & np.isfinite(row)
            & (col >= 0)
            & (row >= 0)
            & (col < self.width - 1)
            & (row < self.height - 1)
        )
        ci = np.floor(np.where(inside, col, 0)).astype(int)
        ri = np.floor(np.where(inside, row, 0)).astype(int)
        corners = np.array(
            [
                self.data[ri, ci],
                self.data[ri, ci + 1],
                self.data[ri + 1, ci],
                self.data[ri + 1, ci + 1],
            ]
        )
        valid = inside & np.all(np.isfinite(corners), axis=0)
        fx, fy = col - ci, row - ri
        z = (
            corners[0] * (1 - fx) * (1 - fy)
            + corners[1] * fx * (1 - fy)
            + corners[2] * (1 - fx) * fy
            + corners[3] * fx * fy
        )
        reasons = np.where(~inside, "SOURCE_BOUNDARY", np.where(valid, "VALID", "NODATA"))
        return np.where(valid, z, np.nan), reasons

    def compute_horizon(self, cell_id, observer_height_m, azimuths_deg):
        """Return requested rays in input order (azimuths normalized modulo 360).

        Heights are radial metres above DEM terrain sampled at the original cell
        center. The first invalid interpolation ends the supported sample prefix.
        """
        height = float(observer_height_m)
        if not math.isfinite(height) or height < 0:
            raise ValueError("Observer height must be finite and nonnegative")
        azimuths = tuple(float(a) for a in azimuths_deg)
        if not azimuths or len(azimuths) > 20000 or not all(map(math.isfinite, azimuths)):
            raise ValueError("Provide 1..20000 finite azimuths")
        azimuths = tuple(a % 360 for a in azimuths)
        if cell_id not in self.cells:
            raise TerrainUnavailable(f"Unknown original cell ID: {cell_id}")
        cell = self.cells[cell_id]
        lat, lon = float(cell["latitude_deg"]), float(cell["longitude_east_deg"])
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 < lat < 90:
            raise TerrainUnavailable("Invalid observer or undefined azimuth at exact pole")
        x, y = self.forward.transform(lon, lat)
        # PROJ spherical stereographic inversion loses millimetres extremely near
        # the pole (e.g. a point 5 cm away). This tolerance is numerical, not DEM accuracy.
        if "x_m" in cell and math.hypot(x - cell["x_m"], y - cell["y_m"]) > 0.01:
            raise TerrainUnavailable("Original geographic/projected cell centers disagree")
        key = json.dumps(
            [
                cell_id,
                cell,
                self.digest,
                height,
                azimuths,
                asdict(self.references),
                self.sample_step_m,
                ALGORITHM_VERSION,
            ],
            sort_keys=True,
            allow_nan=False,
        )
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return copy.deepcopy(self._cache[key])
        z, reason = self._sample([x], [y])
        if not np.isfinite(z[0]):
            raise TerrainUnavailable(f"Observer interpolation invalid: {reason[0]}")
        ground = float(z[0])
        radius = self.references.radius_m
        offset = self.references.height_offset_m
        observer_radius = radius + ground + offset + height
        # The local polar footprint is bounded well inside this search budget.
        # Reaching the budget is still UNKNOWN, never a full-horizon certificate.
        diagonal = math.hypot(self.bounds[2] - self.bounds[0], self.bounds[3] - self.bounds[1])
        max_distance = min(2 * diagonal, math.pi * radius / 2)
        distances = np.arange(
            self.sample_step_m, max_distance + self.sample_step_m, self.sample_step_m
        )
        rays = []
        unique = {}
        for az in azimuths:
            if az in unique:
                rays.append(copy.deepcopy(unique[az]))
                continue
            lons, lats, _ = self.geod.fwd(
                np.full(distances.size, lon),
                np.full(distances.size, lat),
                np.full(distances.size, az),
                distances,
            )
            xs, ys = self.forward.transform(lons, lats)
            values, reasons = self._sample(xs, ys)
            invalid = np.flatnonzero(~np.isfinite(values))
            count = int(invalid[0]) if invalid.size else len(values)
            stop = str(reasons[count]) if invalid.size else "SEARCH_LIMIT"
            angles = elevation_angle(
                distances[:count], observer_radius, radius + values[:count] + offset, radius
            )
            peak = int(np.argmax(angles)) if count else None
            obstruction = None
            lower_bound = None
            if peak is not None:
                obstruction = dict(
                    distance_m=float(distances[peak]),
                    source_x_m=float(xs[peak]),
                    source_y_m=float(ys[peak]),
                    latitude_deg=float(lats[peak]),
                    longitude_east_deg=float(lons[peak] % 360),
                    source_elevation_m=float(values[peak]),
                    radius_m=float(radius + values[peak] + offset),
                )
                error = self.references.elevation_error_bound_m
                if error is not None:
                    lower = elevation_angle(
                        distances[:count],
                        observer_radius + error,
                        radius + values[:count] + offset - error,
                        radius,
                    )
                    lower_bound = float(np.max(lower))
            ray = dict(
                azimuth_deg=az,
                terrain_horizon_elevation_deg=float(angles[peak]) if peak is not None else None,
                obstruction_distance_m=obstruction["distance_m"] if obstruction else None,
                obstruction=obstruction,
                controlling_obstruction_distance_m=obstruction["distance_m"] if obstruction else None,
                controlling_obstruction_elevation_m=obstruction["source_elevation_m"] if obstruction else None,
                supported_radius_m=float(distances[count - 1]) if count else 0,
                supported_sample_count=count,
                supported_sample_interval_m=[self.sample_step_m, float(distances[count - 1])]
                if count
                else None,
                first_unknown_distance_m=float(distances[count])
                if invalid.size
                else float(max_distance),
                stop_reason=stop,
                coverage="PARTIAL" if count else "UNKNOWN",
                near_field_complete=False,
                far_field_complete=False,
                resolution_verified=False,
                uncertainty_deg=None,
                verified_obstruction_lower_bound_deg=lower_bound,
                sampling_step_m=self.sample_step_m,
                angular_interpolation=False,
            )
            unique[az] = ray
            rays.append(copy.deepcopy(ray))
        result = dict(
            cell_id=cell_id,
            observer_height_m=height,
            model="TERRAIN_PARTIAL",
            algorithm_version=ALGORITHM_VERSION,
            far_field_complete=False,
            coverage="PARTIAL" if any(r["supported_sample_count"] for r in rays) else "UNKNOWN",
            azimuth_samples=rays,
            max_supported_radius_m=max(r["supported_radius_m"] for r in rays),
            observer_ground_height_m=ground,
            observer_radius_m=observer_radius,
            observation_position=dict(latitude_deg=lat, longitude_east_deg=lon, x_m=x, y_m=y),
            vertical_reference_verified=self.references.vertical_reference_verified,
            reference_settings=asdict(self.references),
            azimuth_convention=AZIMUTH_CONVENTION,
            sampling_step_m=self.sample_step_m,
            angular_resolution_deg=None,
            direction_mode="EXACT_REQUESTED_AZIMUTHS",
            source_provenance=self.provenance,
            raster_sha256=self.digest,
            source_manifest=self.provenance,
            raster_metadata=self.raster_metadata,
            target_treatment="CENTER_ONLY",
            limitations=[
                "Finite local DEM cannot certify a clear lunar far field.",
                "Bilinear samples form a discrete skyline lower estimate, not a continuous upper bound.",
                "The open interval from observer to first sample and subpixel terrain remain unresolved.",
                "No finite angular error bound follows from pixel size or a sampling convergence check.",
                "Target centers only: no solar disk fraction, full illumination or Earth disk treatment.",
            ],
        )
        if not self.references.vertical_reference_verified:
            result["limitations"].append(
                "CONDITIONAL DIAGNOSTIC: DEM Z assumed radial above the declared sphere; "
                "vertical conversion is unverified. Physical visibility must remain UNKNOWN."
            )
        if self.cache_size:
            with self._cache_lock:
                self._cache[key] = copy.deepcopy(result)
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
        return copy.deepcopy(result)

    def diagnostic_skyline(self, cell_id, observer_height_m=1.0, angular_resolution_deg=1.0):
        step = float(angular_resolution_deg)
        if not math.isfinite(step) or not 0.018 <= step <= 360:
            raise ValueError("Diagnostic angular resolution must be 0.018..360 degrees")
        result = self.compute_horizon(cell_id, observer_height_m, np.arange(0, 360, step))
        result.update(angular_resolution_deg=step, direction_mode="DIAGNOSTIC_SKYLINE")
        return result


def classify_visibility(ray, elevation_deg, *, reference_compatible):
    """Three-state target-center decision; unknown error bounds cannot certify a block."""
    if (
        not reference_compatible
        or ray is None
        or elevation_deg is None
        or not math.isfinite(elevation_deg)
        or not -90 <= elevation_deg <= 90
    ):
        return "UNKNOWN"
    lower = ray.get("verified_obstruction_lower_bound_deg")
    if lower is not None and math.isfinite(lower) and elevation_deg < lower:
        return "TERRAIN_BLOCKED"
    upper = ray.get("verified_horizon_upper_bound_deg")
    if (
        ray.get("far_field_complete")
        and ray.get("near_field_complete")
        and ray.get("resolution_verified")
        and upper is not None
        and math.isfinite(upper)
        and elevation_deg > upper
    ):
        return "TERRAIN_VISIBLE"
    return "UNKNOWN"
