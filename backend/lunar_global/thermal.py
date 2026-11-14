"""Historical Diviner GCP bins. No thermal predictions or cross-time averaging."""

import csv
import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .grid import FRAME, RADIUS_M
from .sources import SourceProduct, label_value
from .storage import query, sha256, write_json

NAME = "global_cumul_avg_cyl_90s80s_002"
BASE = "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_gcp/"


def ingest_diviner(root):
    directory = Path(root) / "source_products/diviner"
    label = (directory / (NAME + ".lbl")).read_text()
    for key, value in dict(
        DATA_SET_ID="LRO-L-DLRE-5-GCP-V1.0",
        PRODUCT_VERSION_ID="1",
        ROWS="1382400",
        MINIMUM_LATITUDE="-90.00000",
        MAXIMUM_LATITUDE="-80.00000",
        A_AXIS_RADIUS="1737.4",
        POSITIVE_LONGITUDE_DIRECTION="EAST",
    ).items():
        if label_value(label, key) != value:
            raise ValueError(f"Unsupported Diviner metadata {key}")
    path = directory / (NAME + ".tab")
    receipt = json.loads(path.with_suffix(".tab.receipt.json").read_text())
    if sha256(path) != receipt["sha256"]:
        raise ValueError("Diviner source checksum mismatch")
    source = SourceProduct(
        source_id="DIVINER:GCP:90S80S:v1:" + receipt["sha256"][:16],
        organization="NASA / UCLA / PDS Geosciences",
        mission="LRO",
        instrument="Diviner",
        product_name="South polar cumulative brightness temperatures",
        product_identifier=label_value(label, "PRODUCT_ID"),
        version="1",
        canonical_url=BASE + NAME + ".tab",
        access_method="PDS fixed ASCII table with DLRE_GCP.FMT",
        product_type="thermal",
        coordinate_frame=FRAME,
        latitude_type="planetocentric_spherical",
        longitude_convention="east_positive_0_360",
        projection="Cylindrical 0.5 degree spatial bins; input longitude [-180,180], normalized by modulo 360",
        vertical_reference="Not applicable to brightness temperature",
        reference_radius_m=RADIUS_M,
        spatial_resolution_m=math.pi * RADIUS_M / 360,
        temporal_coverage={
            "start": label_value(label, "START_TIME"),
            "stop": label_value(label, "STOP_TIME"),
            "local_time_bin_hours": 0.25,
            "simultaneous": False,
        },
        footprint={"west": 0, "east": 360, "south": -90, "north": -80},
        units="K",
        nodata="-9999 unknown; -9998 invalid",
        quality="HISTORICAL_LOCAL_TIME_BIN_AVERAGE",
        uncertainty=None,
        processing_level="GCP derived; calibration software 4.0",
        download_timestamp=receipt["downloaded_utc"],
        source_checksum=receipt["sha256"],
        label_checksum=sha256(directory / (NAME + ".lbl")),
        citation="Williams et al. 2017, Icarus 283, 300–325; LRO-L-DLRE-5-GCP-V1.0",
        access_conditions="Public NASA PDS; retain attribution",
        status="VERIFIED",
        limitations=[
            "2009–2015 observations; not a prediction for a mission date",
            "Negative temperatures indicate below-sensitivity radiance; retained with quality flag",
            "0.5 degree native support; not 100 m thermal terrain",
            "Local-time centers are rounded in source table",
            "LRO ME/DE421 mission convention: https://svs.gsfc.nasa.gov/4969/",
        ],
    )
    source.validate_alignment()
    target = Path(root) / "thermal_snapshots" / source.source_checksum
    if target.exists():
        raise ValueError("Thermal snapshot already exists")
    target.mkdir(parents=True)
    files, rows, total, part = {}, [], 0, 0

    def flush():
        nonlocal part
        output = target / f"part-{part:04d}.parquet"
        pq.write_table(pa.Table.from_pylist(rows), output, compression="zstd")
        files[output.name] = sha256(output)
        rows.clear()
        part += 1

    with path.open(newline="") as stream:
        reader = csv.reader(stream)
        header = [name.strip() for name in next(reader)]
        if header != ["clon", "clat", "ltim", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "tbol"]:
            raise ValueError("Diviner columns differ from verified FMT")
        for line in reader:
            values = dict(zip(header, map(float, line), strict=True))
            lat, lon, local = values.pop("clat"), values.pop("clon") % 360, values.pop("ltim")
            if not (-90 <= lat < -80 and 0 <= local < 24):
                raise ValueError("Diviner row outside declared spatial/time support")
            row = dict(
                latitude_deg=lat,
                longitude_deg=lon,
                local_time_hours=local,
                local_time_bin=int(local * 4),
                west=lon - 0.25,
                east=lon + 0.25,
                south=lat - 0.25,
                north=lat + 0.25,
                source_id=source.source_id,
            )
            row.update({k: None if v in (-9999, -9998) else v for k, v in values.items()})
            rows.append(row)
            total += 1
            if len(rows) == 16384:
                flush()
    if rows:
        flush()
    if total != 1382400:
        raise ValueError("Diviner table row count mismatch")
    write_json(
        target / "manifest.json",
        dict(
            source=source.model_dump(),
            files=files,
            count=total,
            format_sha256=sha256(directory / "dlre_gcp.fmt"),
        ),
    )
    write_json(directory / "source.json", source.model_dump())
    return total


def thermal_context(root, latitude, longitude, local_time_bin):
    if not 0 <= local_time_bin <= 95:
        raise ValueError("Local-time bin must be 0..95")
    manifests = list((Path(root) / "thermal_snapshots").glob("*/manifest.json"))
    if len(manifests) != 1 or not -90 <= latitude < -80:
        return dict(measurements=[], missing_reason="NO_INGESTED_THERMAL_COVERAGE", source=None)
    from .storage import verified_files

    files, manifest = verified_files(manifests[0].parent)
    lon = longitude % 360
    rows = query(
        files,
        "south <= ? AND north > ? AND west <= ? AND east > ? AND local_time_bin = ?",
        [latitude, latitude, lon, lon, local_time_bin],
        limit=10,
        order="longitude_deg, latitude_deg",
    )
    for row in rows:
        row["quality_flags"] = {
            key: (
                "MISSING"
                if row[key] is None
                else "BELOW_SENSITIVITY"
                if row[key] < 0
                else "OBSERVED_BIN_MEAN"
            )
            for key in ["t3", "t4", "t5", "t6", "t7", "t8", "t9", "tbol"]
        }
    return dict(
        measurements=rows,
        missing_reason=None if rows else "NO_OBSERVATION_BIN",
        source=manifest["source"],
        support="Native 0.5 degree pixel containing selected center; regional context only; not a cell mean",
    )
