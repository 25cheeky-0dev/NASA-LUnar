"""Small equirectangular visual products from stored scientific values."""

import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import rasterio
from astropy import units as u
from rasterio.io import MemoryFile

from .grid import hpx
from .service import GlobalStore
from .storage import query, sha256, verified_files, write_json

FIELDS = {
    "elevation_m": ("m", -9000, 11000),
    "slope_deg": ("degree", 0, 30),
    "roughness_m": ("m", 0, 1000),
    "elevation_m_coverage": ("fraction", 0, 1),
}


def build_layers(root):
    root = Path(root)
    store = GlobalStore(root)
    files, manifest = store.feature_files(128)
    if not files:
        raise ValueError("LOLA features must be ingested first")
    target = root / "visualization_tiles"
    target.mkdir(parents=True, exist_ok=True)
    lon, lat = np.meshgrid((np.arange(720) + 0.5) / 2, 90 - (np.arange(360) + 0.5) / 2)
    pixels = hpx(128).lonlat_to_healpix(lon * u.deg, lat * u.deg)
    entries = []
    for field, (units, low, high) in FIELDS.items():
        values = np.full(hpx(128).npix, np.nan)
        for path in files:
            for batch in pq.ParquetFile(path).iter_batches(columns=["pixel", field]):
                data = batch.to_pydict()
                values[np.asarray(data["pixel"])] = np.asarray(data[field], dtype=float)
        image = values[pixels]
        fraction = np.clip((image - low) / (high - low), 0, 1)
        color = np.zeros((4, 360, 720), dtype=np.uint8)
        valid = np.isfinite(image)
        fraction = np.nan_to_num(fraction)
        color[0] = (30 + 220 * fraction).astype(np.uint8)
        color[1] = (65 + 140 * fraction).astype(np.uint8)
        color[2] = (110 - 65 * fraction).astype(np.uint8)
        color[3] = valid.astype(np.uint8) * 255
        path = target / f"{field}.png"
        if path.exists():
            raise ValueError("Visualization snapshot already exists")
        with MemoryFile() as memory:
            with memory.open(
                driver="PNG", width=720, height=360, count=4, dtype="uint8"
            ) as dataset:
                dataset.write(color)
            path.write_bytes(memory.read())
        entries.append(
            dict(
                layer_id=field,
                units=units,
                minimum=low,
                maximum=high,
                color_legend=["#1e416e", "#facd2d"],
                source_id=manifest["source"]["source_id"],
                snapshot_id=manifest["snapshot_id"],
                native_resolution_m=7580.84,
                status="AVAILABLE",
                nodata="Transparent",
                uncertainty="UNKNOWN",
                projection="Equirectangular, 0..360 east, 90..-90 latitude",
                rendering="Nearest HEALPix cell at display pixel center; visualization sampling only",
                file=path.name,
                sha256=sha256(path),
            )
        )
    for field in ("thermal", "spectral"):
        entries.append(
            dict(layer_id=field, status="UNAVAILABLE", reason="No verified ingested observations")
        )
    write_json(target / "layers.json", entries)
    return entries


def add_context_layers(root):
    root = Path(root)
    target = root / "visualization_tiles"
    entries = json.loads((target / "layers.json").read_text())
    manifests = list((root / "thermal_snapshots").glob("*/manifest.json"))
    if len(manifests) != 1:
        raise ValueError("One explicit thermal snapshot required")
    paths, manifest = verified_files(manifests[0].parent)
    values = np.full((360, 720), np.nan)
    for offset in range(0, 14400, 1000):
        rows = query(
            paths, "local_time_bin=0", limit=1000, offset=offset, order="latitude_deg,longitude_deg"
        )
        for row in rows:
            if row["tbol"] is not None and row["tbol"] >= 0:
                y = int((90 - row["latitude_deg"]) * 2)
                x = int(row["longitude_deg"] * 2) % 720
                values[y, x] = row["tbol"]
    normalized = np.nan_to_num(np.clip((values - 50) / 300, 0, 1))
    color = np.zeros((4, 360, 720), dtype=np.uint8)
    color[0] = (30 + 220 * normalized).astype(np.uint8)
    color[1] = (65 + 140 * normalized).astype(np.uint8)
    color[2] = (110 - 65 * normalized).astype(np.uint8)
    color[3] = np.isfinite(values).astype(np.uint8) * 255
    path = target / "thermal.png"
    if path.exists():
        raise ValueError("Thermal visualization snapshot already exists")
    with MemoryFile() as memory:
        with memory.open(driver="PNG", width=720, height=360, count=4, dtype="uint8") as raster:
            raster.write(color)
        path.write_bytes(memory.read())
    entries = [row for row in entries if row["layer_id"] != "thermal"]
    entries.append(
        dict(
            layer_id="thermal",
            units="K; local-time bin 0 (00:00–00:15), 2009–2015",
            minimum=50,
            maximum=350,
            source_id=manifest["source"]["source_id"],
            snapshot_id=manifest["source"]["source_checksum"],
            native_resolution_m=manifest["source"]["spatial_resolution_m"],
            status="AVAILABLE",
            nodata="Transparent; includes below-sensitivity negative values",
            uncertainty="UNKNOWN",
            projection="Equirectangular 0..360 east; only 90S..80S coverage",
            file=path.name,
            sha256=sha256(path),
            rendering="Native historical bolometric bins; not landing-date temperature",
        )
    )
    write_json(target / "layers-v2.json", entries)
    (target / "layers.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return entries


def add_imagery_layer(root):
    root = Path(root)
    target = root / "visualization_tiles"
    entries = json.loads((target / "layers.json").read_text())
    source = json.loads((root / "source_products/lroc/source.json").read_text())
    raw = root / "source_products/lroc/WAC_GLOBAL_E000N1800_004P.IMG"
    if sha256(raw) != source["source_checksum"]:
        raise ValueError("Imagery checksum mismatch")
    with rasterio.open(raw) as raster:
        values = raster.read(1, out_shape=(360, 720))
    valid = np.isfinite(values) & (values > -3e38)
    low, high = np.percentile(values[valid], [1, 99])
    gray = (np.clip((values - low) / (high - low), 0, 1) * 255).astype(np.uint8)
    color = np.stack([gray, gray, gray, valid.astype(np.uint8) * 255])
    path = target / "lroc.png"
    if path.exists():
        raise ValueError("Imagery visualization already exists")
    with MemoryFile() as memory:
        with memory.open(driver="PNG", width=720, height=360, count=4, dtype="uint8") as raster:
            raster.write(color)
        path.write_bytes(memory.read())
    entries.append(
        dict(
            layer_id="lroc",
            units="stored image DN; display contrast only",
            minimum=float(low),
            maximum=float(high),
            status="AVAILABLE",
            source_id=source["source_id"],
            snapshot_id=source["source_checksum"],
            native_resolution_m=source["spatial_resolution_m"],
            uncertainty="UNKNOWN",
            nodata="Transparent",
            projection="Equirectangular 0..360 east",
            file=path.name,
            sha256=sha256(path),
            rendering="Nearest native image pixel, 1st–99th percentile grayscale stretch; not terrain physics",
        )
    )
    coverage = next(row for row in entries if row["layer_id"] == "elevation_m_coverage")
    entries.append(
        dict(
            coverage,
            layer_id="quality",
            units="category 1: interpolated altimetry; uncertainty UNKNOWN",
            minimum=1,
            maximum=1,
            rendering="Uniform category from stored source quality; not a numeric confidence score",
        )
    )
    write_json(target / "layers-v3.json", entries)
    (target / "layers.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return entries
