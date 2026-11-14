"""Verified LROC visual context, explicitly excluded from terrain vectors."""

import hashlib
from pathlib import Path

import numpy as np
import rasterio

from .grid import FRAME, RADIUS_M
from .sources import SourceProduct, download, label_value
from .storage import sha256, write_json

LROC_URL = "https://pds.mcp.nasa.gov/data/store/img/lunar_reconnaissance_orbiter/pds4/lroc/lro-l-lroc-5-rdr/LROLRC_2001/DATA/BDR/WAC_GLOBAL/WAC_GLOBAL_E000N1800_004P.IMG"
FRAME_EVIDENCE = "https://svs.gsfc.nasa.gov/4969/"


def register_lroc(root):
    directory = Path(root) / "source_products" / "lroc"
    path, receipt = download(LROC_URL, directory)
    with path.open("rb") as stream:
        label_bytes = stream.read(5760)
    label = label_bytes.decode("ascii")
    expected = dict(
        PRODUCT_ID="WAC_GLOBAL_E000N1800_004P",
        PRODUCT_VERSION_ID="v1.3",
        TARGET_NAME="MOON",
        SAMPLE_TYPE="PC_REAL",
        SAMPLE_BITS="32",
        LINES="720",
        LINE_SAMPLES="1440",
        PROJECTION_LATITUDE_TYPE="PLANETOCENTRIC",
        MAP_PROJECTION_TYPE="EQUIRECTANGULAR",
        POSITIVE_LONGITUDE_DIRECTION="EAST",
    )
    for key, value in expected.items():
        if label_value(label, key) != value:
            raise ValueError(f"Unsupported imagery field {key}")
    with rasterio.open(path) as raster:
        from pyproj import CRS

        crs = CRS.from_wkt(raster.crs.to_wkt())
        if crs.ellipsoid.semi_major_metre != RADIUS_M or crs.ellipsoid.inverse_flattening != 0:
            raise ValueError("Imagery sphere mismatch")
        if abs(raster.transform.a - np.pi * RADIUS_M / 720) > 1e-7 or raster.transform.c != 0:
            raise ValueError("Imagery georeferencing mismatch")
    source = SourceProduct(
        source_id="LROC:WAC_GLOBAL_E000N1800_004P:v1.3:" + receipt["sha256"][:16],
        organization="NASA / Arizona State University / PDS Imaging",
        mission="LRO",
        instrument="LROC WAC",
        product_name="WAC Global Morphologic Map",
        product_identifier=expected["PRODUCT_ID"],
        version="v1.3",
        canonical_url=LROC_URL,
        access_method="PDS attached label IMG via migrated official archive",
        product_type="imagery",
        coordinate_frame=FRAME,
        latitude_type="planetocentric_spherical",
        longitude_convention="east_positive_0_360",
        projection="EQUIRECTANGULAR",
        vertical_reference="Not applicable to image DN",
        reference_radius_m=RADIUS_M,
        spatial_resolution_m=7580.837606037399,
        temporal_coverage={
            "start": label_value(label, "START_TIME"),
            "stop": label_value(label, "STOP_TIME"),
            "simultaneous": False,
        },
        footprint={"west": 0, "east": 360, "south": -90, "north": 90},
        units="stored image DN; radiometric unit not declared in this label",
        nodata="PDS CORE_* special float bit patterns FF7FFFFB through FF7FFFFF",
        quality="PHOTOMETRIC_MOSAIC_VISUAL_CONTEXT",
        uncertainty=None,
        processing_level="RDR",
        download_timestamp=receipt["downloaded_utc"],
        source_checksum=receipt["sha256"],
        label_checksum=hashlib.sha256(label_bytes).hexdigest(),
        citation="Speyerer et al. 2011, LPSC abstract 2387; WAC_GLOBAL v1.3",
        access_conditions="Public NASA PDS archive; retain LROC attribution",
        status="VERIFIED",
        limitations=[
            "Visual context only; not terrain or hazard evidence",
            "Multiple historical illumination conditions",
            "Frame mapping follows NASA LRO mission-wide ME/DE421 convention: " + FRAME_EVIDENCE,
            "No per-pixel positional uncertainty supplied",
        ],
    )
    source.validate_alignment()
    manifest = directory / "source.json"
    if not manifest.exists():
        write_json(manifest, source.model_dump())
    elif SourceProduct.model_validate_json(manifest.read_text()) != source:
        raise ValueError("Imagery registration changed")
    return source


def context(root, latitude, longitude):
    directory = Path(root) / "source_products" / "lroc"
    if not (directory / "source.json").exists():
        return None
    source = SourceProduct.model_validate_json((directory / "source.json").read_text())
    source.validate_alignment()
    path = directory / "WAC_GLOBAL_E000N1800_004P.IMG"
    if sha256(path) != source.source_checksum:
        raise ValueError("Imagery checksum mismatch")
    row = min(719, max(0, int((90 - latitude) * 4)))
    col = int((longitude % 360) * 4) % 1440
    with rasterio.open(path) as raster:
        value = float(raster.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
    valid = np.isfinite(value) and value > -3e38
    return dict(
        source=source.model_dump(),
        value=value if valid else None,
        missing_reason=None if valid else "PDS_SPECIAL_PIXEL",
        units=source.units,
        native_resolution_m=source.spatial_resolution_m,
        pixel_footprint=dict(
            west=col / 4, east=(col + 1) / 4, north=90 - row / 4, south=90 - (row + 1) / 4
        ),
        support="Source pixel containing selected cell center; visual regional context, not cell mean",
    )
