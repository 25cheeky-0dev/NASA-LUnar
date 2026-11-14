"""Native DEM derivatives followed by equal-area spherical quadrature.

No slope is computed from the averaged HEALPix elevation surface. Quadrature
samples nested child centers; each sample represents exactly equal spherical
area. Extremes/counts describe sampled source pixels, not exhaustive extrema.
"""

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from astropy import units as u
from astropy_healpix import HEALPix

from app.integration.vector_contract import FEATURES, NORMALIZATION

from .grid import RADIUS_M, cell_id, hpx
from .sources import SourceProduct
from .storage import sha256, write_json

SCALES = NORMALIZATION["scales"]
METHOD = "ldem4-native-central-gradient-3x3std-hpx-quadrature-v1"


def native_terrain(image, source):
    source.validate_alignment()
    if sha256(image) != source.source_checksum:
        raise ValueError("Source checksum mismatch")
    raw = np.memmap(image, dtype="<i2", mode="r", shape=(720, 1440))
    if np.any((raw < -17758) | (raw > 21008)):
        raise ValueError("Pixels outside declared LOLA range; missing/invalid source")
    z = np.asarray(raw, dtype=np.float64) * 0.5
    step = math.radians(0.25)
    lat = np.radians(90 - (np.arange(720) + 0.5) / 4)
    dx = RADIUS_M * step * np.cos(lat[:, None])
    east = (np.roll(z, -1, axis=1) - np.roll(z, 1, axis=1)) / (2 * dx)
    north = (np.roll(z, 1, axis=0) - np.roll(z, -1, axis=0)) / (2 * RADIUS_M * step)
    slope = np.degrees(np.arctan(np.hypot(east, north)))
    total, squares = np.zeros_like(z), np.zeros_like(z)
    for dy in (-1, 0, 1):
        for dx_shift in (-1, 0, 1):
            neighbor = np.roll(np.roll(z, dy, axis=0), dx_shift, axis=1)
            total += neighbor
            squares += neighbor**2
    roughness = np.sqrt(np.maximum(squares / 9 - (total / 9) ** 2, 0))
    slope[[0, -1], :] = np.nan
    roughness[[0, -1], :] = np.nan
    return z, slope, roughness


def aggregate_pixels(pixels, nside, native, subdivision=16):
    if subdivision not in (4, 8, 16, 32) or len(pixels) > 512:
        raise ValueError("Quadrature exceeds batch budget")
    count = subdivision**2
    child = HEALPix(nside=nside * subdivision, order="nested")
    indices = np.asarray(pixels)[:, None] * count + np.arange(count)[None, :]
    lon, lat = child.healpix_to_lonlat(indices)
    rows = np.clip(np.floor((90 - lat.to_value(u.deg)) * 4).astype(int), 0, 719)
    cols = np.floor((lon.to_value(u.deg) % 360) * 4).astype(int) % 1440
    fields = {}
    for name, values in zip(FEATURES, native):
        samples = values[rows, cols]
        valid = np.isfinite(samples)
        coverage = valid.mean(axis=1)
        sums = np.where(valid, samples, 0).sum(axis=1)
        means = np.divide(
            sums, valid.sum(axis=1), out=np.full(len(pixels), np.nan), where=valid.sum(axis=1) > 0
        )
        fields[name] = means
        fields[name + "_coverage"] = coverage
        if name == "elevation_m":
            fields["sampled_minimum_elevation_m"] = samples.min(axis=1)
            fields["sampled_maximum_elevation_m"] = samples.max(axis=1)
            fields["elevation_variability_m"] = samples.std(axis=1)
    fields["sampled_source_pixel_count"] = np.array(
        [len(np.unique(r * 1440 + c)) for r, c in zip(rows, cols)]
    )
    return fields


def physical_vector(record):
    values = [record.get(name) for name in FEATURES]
    return dict(
        feature_set="terrain-v1",
        feature_names=FEATURES,
        units=["m", "degree", "m"],
        raw_values=values,
        normalized_values=[None if v is None else v / s for v, s in zip(values, SCALES)],
        missing_mask=[v is None for v in values],
        normalization_metadata=dict(
            version="physical-scales-v1",
            scales=SCALES,
            offsets=[0, 0, 0],
            interpretation="Descriptive fixed numerical scales; not engineering safety thresholds",
        ),
        source_id=record["source_id"],
        snapshot_id=record["snapshot_id"],
        quality=record["quality"],
    )


def fit_zscore(rows, snapshot_id):
    ordered = sorted(rows, key=lambda row: row["cell_id"])
    if not ordered or any(any(row.get(k) is None for k in FEATURES) for row in ordered):
        raise ValueError("Z-score fit requires an explicit nonempty complete population")
    matrix = np.array([[row[k] for k in FEATURES] for row in ordered], dtype=float)
    if not np.isfinite(matrix).all():
        raise ValueError("Nonfinite fit population")
    std = matrix.std(axis=0, ddof=0)
    if np.any(std == 0):
        raise ValueError("Constant feature cannot define a z-score distance")
    fit = dict(
        version="population-zscore-v1",
        snapshot_id=snapshot_id,
        population_cell_ids=[row["cell_id"] for row in ordered],
        population_sha256=hashlib.sha256(matrix.tobytes()).hexdigest(),
        features=FEATURES,
        means=matrix.mean(axis=0).tolist(),
        standard_deviations=std.tolist(),
        ddof=0,
    )
    fit["fit_sha256"] = hashlib.sha256(json.dumps(fit, sort_keys=True).encode()).hexdigest()
    return fit


def ingest_lola(root, nside=128, subdivision=16):
    root = Path(root)
    source_dir = root / "source_products" / "lola"
    source = SourceProduct.model_validate_json((source_dir / "source.json").read_text())
    native = native_terrain(source_dir / "ldem_4.img", source)
    snapshot = hashlib.sha256(
        f"{source.source_checksum}:{METHOD}:{nside}:{subdivision}".encode()
    ).hexdigest()
    target = root / "feature_snapshots" / f"nside={nside}" / snapshot
    if target.exists():
        raise ValueError("Feature snapshot already exists")
    target.mkdir(parents=True)
    manifest = dict(
        snapshot_id=snapshot,
        source=source.model_dump(),
        nside=nside,
        method=METHOD,
        quadrature_samples_per_cell=subdivision**2,
        files={},
        slope="Central east/north finite differences on source DEM; spherical metric; outer polar rows null",
        roughness="Population standard deviation of 3x3 native source heights; not detrended; polar rows null",
        aggregation="Equal-area nested HEALPix child-center quadrature; piecewise constant source pixels",
        limitations=[
            "Quadrature approximation, not exact polygon integration",
            "Min/max and counts cover sampled source pixels only",
            "Native east-west spacing shrinks with latitude; derivative accuracy is unknown",
        ],
    )
    for start in range(0, hpx(nside).npix, 512):
        pixels = np.arange(start, min(start + 512, hpx(nside).npix))
        fields = aggregate_pixels(pixels, nside, native, subdivision)
        lon, lat = hpx(nside).healpix_to_lonlat(pixels)
        rows = []
        for index, pixel in enumerate(pixels):
            record = dict(
                cell_id=cell_id(nside, int(pixel)),
                pixel=int(pixel),
                longitude_deg=float(lon[index].to_value(u.deg)),
                latitude_deg=float(lat[index].to_value(u.deg)),
                source_id=source.source_id,
                snapshot_id=snapshot,
                quality=source.quality,
                native_resolution_m=source.spatial_resolution_m,
                effective_analysis_resolution_m=max(
                    source.spatial_resolution_m,
                    math.sqrt(4 * math.pi * RADIUS_M**2 / hpx(nside).npix),
                ),
                method=METHOD,
                uncertainty=None,
            )
            record.update(
                {
                    key: (float(value[index]) if np.isfinite(value[index]) else None)
                    for key, value in fields.items()
                }
            )
            record["raw_values"] = [record[key] for key in FEATURES]
            record["normalized_values"] = physical_vector(record)["normalized_values"]
            record["missing_mask"] = physical_vector(record)["missing_mask"]
            rows.append(record)
        path = target / f"part-{start:08d}.parquet"
        pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")
        manifest["files"][path.name] = sha256(path)
    write_json(target / "manifest.json", manifest)
    return manifest
