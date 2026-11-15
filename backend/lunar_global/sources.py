"""Source registration precedes ingestion. Unverified products cannot be fused."""

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
import truststore
from pydantic import BaseModel, ConfigDict, Field

from .grid import FRAME, RADIUS_M
from .storage import sha256, write_json

LOLA_BASE = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/img/"
OFFICIAL_HOSTS = {
    "pds.mcp.nasa.gov",
    "pds-geosciences.wustl.edu",
    "pgda.gsfc.nasa.gov",
    "data.lroc.im-ldi.com",
    "pds.lroc.im-ldi.com",
    "www.diviner.ucla.edu",
    "pds-imaging.jpl.nasa.gov",
}


class SourceProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source_id: str
    organization: str
    mission: str
    instrument: str
    product_name: str
    product_identifier: str
    version: str
    canonical_url: str
    access_method: str
    product_type: str
    coordinate_frame: str
    latitude_type: str
    longitude_convention: str
    projection: str
    vertical_reference: str
    reference_radius_m: float
    spatial_resolution_m: float = Field(gt=0)
    temporal_coverage: dict
    footprint: dict
    units: str
    nodata: str
    quality: str
    uncertainty: str | None
    processing_level: str
    download_timestamp: str
    source_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    label_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    citation: str
    access_conditions: str
    limitations: list[str]
    status: Literal["VERIFIED", "UNAVAILABLE"]

    def validate_alignment(self):
        if (
            self.coordinate_frame != FRAME
            or self.reference_radius_m != RADIUS_M
            or self.latitude_type != "planetocentric_spherical"
            or self.longitude_convention != "east_positive_0_360"
        ):
            raise ValueError("No verified transformation for this source frame/sphere/convention")


def download(url, directory, maximum_bytes=64 * 1024 * 1024):
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in OFFICIAL_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not Path(parsed.path).name
    ):
        raise ValueError("Source download requires an approved official HTTPS archive")
    target = Path(directory) / Path(parsed.path).name
    target.parent.mkdir(parents=True, exist_ok=True)
    receipt = target.with_suffix(target.suffix + ".receipt.json")
    if target.exists():
        existing = json.loads(receipt.read_text())
        if existing["url"] != url or sha256(target) != existing["sha256"]:
            raise ValueError("Cached source checksum mismatch")
        return target, existing
    temporary = target.with_suffix(target.suffix + "." + uuid.uuid4().hex + ".partial")
    count = 0
    import ssl

    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        with httpx.Client(verify=context, timeout=120, follow_redirects=False) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with temporary.open("xb") as stream:
                    for chunk in response.iter_bytes():
                        count += len(chunk)
                        if count > maximum_bytes:
                            raise ValueError("Source download exceeds byte budget")
                        stream.write(chunk)
        evidence = dict(
            url=url,
            sha256=sha256(temporary),
            bytes=count,
            downloaded_utc=datetime.now(UTC).isoformat(),
            authentication="TLS official archive; locally computed SHA256, not publisher signature",
        )
        temporary.rename(target)
        write_json(receipt, evidence)
        return target, evidence
    finally:
        temporary.unlink(missing_ok=True)


def label_value(label, name):
    matches = re.findall(r"^\s*" + re.escape(name) + r"\s*=\s*([^\r\n]+)", label, re.M)
    if len(matches) != 1:
        raise ValueError(f"Missing/ambiguous label field {name}")
    return matches[0].split(" <")[0].strip().strip('"')


def register_lola(directory):
    label_path, label_receipt = download(LOLA_BASE + "ldem_4.lbl", directory)
    label = label_path.read_text()
    expected = dict(
        PRODUCT_ID="LDEM_4",
        PRODUCT_VERSION_ID="V3.0",
        TARGET_NAME="MOON",
        SAMPLE_TYPE="LSB_INTEGER",
        SAMPLE_BITS="16",
        UNIT="METER",
        LINES="720",
        LINE_SAMPLES="1440",
        SCALING_FACTOR="0.5",
        OFFSET="1737400.",
        MAP_PROJECTION_TYPE="SIMPLE CYLINDRICAL",
        MAP_RESOLUTION="4",
        POSITIVE_LONGITUDE_DIRECTION="EAST",
        COORDINATE_SYSTEM_NAME="MEAN EARTH/POLAR AXIS OF DE421",
        MAXIMUM_LATITUDE="90",
        MINIMUM_LATITUDE="-90",
        WESTERNMOST_LONGITUDE="0",
        EASTERNMOST_LONGITUDE="360",
    )
    for field, value in expected.items():
        if label_value(label, field) != value:
            raise ValueError(f"Unsupported LOLA label: {field}")
    image_path, receipt = download(LOLA_BASE + "ldem_4.img", directory)
    if image_path.stat().st_size != 720 * 1440 * 2:
        raise ValueError("LOLA image length mismatch")
    source = SourceProduct(
        source_id="LOLA:LDEM_4:V3.0:" + receipt["sha256"][:16],
        organization="NASA GSFC / PDS Geosciences",
        mission="LRO",
        instrument="LOLA",
        product_name="Global lunar shape map",
        product_identifier="LDEM_4",
        version="V3.0",
        canonical_url=receipt["url"],
        access_method="PDS3 detached label and little-endian int16 IMG",
        product_type="terrain",
        coordinate_frame=FRAME,
        latitude_type="planetocentric_spherical",
        longitude_convention="east_positive_0_360",
        projection="SIMPLE CYLINDRICAL",
        vertical_reference="Height above 1737400 m reference sphere",
        reference_radius_m=RADIUS_M,
        spatial_resolution_m=7580.84,
        temporal_coverage={
            "start": label_value(label, "START_TIME"),
            "stop": label_value(label, "STOP_TIME"),
        },
        footprint={"west": 0, "east": 360, "south": -90, "north": 90},
        units="m",
        nodata="No special missing constant declared; reject samples outside label MINIMUM/MAXIMUM",
        quality="INTERPOLATED_ALTIMETRY_UNCERTAINTY_UNKNOWN",
        uncertainty=None,
        processing_level="GDR derived",
        download_timestamp=receipt["downloaded_utc"],
        source_checksum=receipt["sha256"],
        label_checksum=label_receipt["sha256"],
        citation="LRO-L-LOLA-4-GDR-V1.0; DOI 10.17189/1520642",
        access_conditions="Public NASA PDS archive; retain source attribution",
        limitations=[
            "Interpolated shape map, not independent shots at every pixel",
            "Possible 45-degree band artifacts",
            "7.58 km nominal latitude spacing is not elevation accuracy",
            "Not local landing terrain or geoid height",
        ],
        status="VERIFIED",
    )
    source.validate_alignment()
    manifest = Path(directory) / "source.json"
    if not manifest.exists():
        write_json(manifest, source.model_dump())
    elif SourceProduct.model_validate_json(manifest.read_text()) != source:
        raise ValueError("Immutable source registration conflict")
    return source, image_path
