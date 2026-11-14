"""Parse labeled Horizons observer CSV, verifying identity and reference frame."""

import csv
import json
import re
from datetime import UTC, datetime

from .data_validation import EphemerisError, angles

PARSER_VERSION = "wispr-observer-csv-1"


def parse_response(raw: bytes, target: int, request):
    try:
        payload = json.loads(raw)
        if payload.get("error"):
            raise EphemerisError("Horizons reported an upstream query error")
        signature = payload.get("signature", {})
        if (
            signature.get("version") not in ("1.2", "1.3")
            or signature.get("source") != "NASA/JPL Horizons API"
        ):
            raise EphemerisError("Unsupported Horizons API signature; review NASA documentation")
        text = payload["result"]
        if text.count("$$SOE") != 1 or text.count("$$EOE") != 1:
            raise EphemerisError("Missing or ambiguous ephemeris delimiters")
        header, rest = text.split("$$SOE")
        table, _ = rest.split("$$EOE")
        name = {10: "Sun", 399: "Earth"}[target]
        for pattern in (
            rf"Target body name:\s*{name}\s*\({target}\)",
            r"Center body name:\s*Moon\s*\(301\)",
            r"Center pole/equ\s*:\s*(?:MOON_ME|MEAN_ME)\b",
            r"Center radii\s*:\s*1737\.4,\s*1737\.4,\s*1737\.4 km",
            r"Atmos refraction:\s*NO \(AIRLESS\)",
        ):
            if not re.search(pattern, header):
                raise EphemerisError("Target, observer, frame or airless convention mismatch")
        match = re.search(
            r"Center geodetic\s*:\s*([\d.eE+-]+),\s*([\d.eE+-]+),\s*([\d.eE+-]+)",
            header,
        )
        if not match:
            raise EphemerisError("Missing observer geodetic coordinates")
        lon, lat, height = map(float, match.groups())
        if (
            abs((lon - request.longitude_east_deg + 180) % 360 - 180) > 1e-4
            or abs(lat - request.latitude_deg) > 1e-4
            or abs(height - request.altitude_km) > 1e-4
        ):
            raise EphemerisError("Observer coordinates or reference height mismatch")
        headings = [
            next(csv.reader([line]))
            for line in header.splitlines()
            if "Date__(UT)" in line and ("Azi_" in line or "Azimuth_" in line)
        ]
        if len(headings) != 1:
            raise EphemerisError("Expected one UT CSV column header")
        labels = [item.strip() for item in headings[0]]

        def column(aliases):
            matches = [i for i, label in enumerate(labels) if label in aliases]
            if len(matches) != 1:
                raise EphemerisError("Missing or ambiguous apparent-angle column")
            return matches[0]

        az = column(("Azi_(a-app)", "Azimuth_(a-app)"))
        el = column(("Elev_(a-app)", "Elevation_(a-app)"))
        date = next(i for i, label in enumerate(labels) if label.startswith("Date__(UT)"))
        records = {}
        previous = None
        for row in csv.reader(table.strip().splitlines()):
            if len(row) != len(labels):
                raise EphemerisError("CSV row length differs from its column header")
            stamp = datetime.strptime(row[date].strip(), "%Y-%b-%d %H:%M:%S").replace(tzinfo=UTC)
            if previous is not None and stamp <= previous:
                raise EphemerisError("Duplicate or nonmonotonic observation time")
            previous = stamp
            values = [row[i].strip() for i in (az, el)]
            if any(value in ("n.a.", "", "--") for value in values):
                records[stamp] = None
            else:
                a, e = map(float, values)
                angles(a, e)
                records[stamp] = (a, e)
        if not records:
            raise EphemerisError("Empty NASA observer table")
        return records
    except EphemerisError:
        raise
    except (ValueError, KeyError, TypeError, IndexError, StopIteration, AttributeError) as exc:
        raise EphemerisError("Malformed or unsupported Horizons observer payload") from exc
