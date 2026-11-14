import json
from datetime import UTC

import pytest

from celestial_engine.data_validation import EphemerisError
from celestial_engine.ephemeris_parser import parse_response

from .conftest import FIXTURES, payload


@pytest.mark.parametrize("target,name", [(10, "sun"), (399, "earth")])
def test_authentic_nasa_fixture(target, name, request_model):
    records = parse_response((FIXTURES / f"{name}.json").read_bytes(), target, request_model)
    assert len(records) == 169
    assert list(records) == request_model.timestamps()
    assert all(stamp.tzinfo == UTC for stamp in records)


@pytest.mark.parametrize(
    "before,after",
    [
        ("$$SOE", "SOE"),
        ("$$EOE", "EOE"),
        ("Sun (10)", "Earth (399)"),
        ("Moon (301)", "Mars (499)"),
        ("MEAN_ME", "IAU_MOON"),
        ("45.0, -89.0", "46.0, -89.0"),
        ("1737.4, 1737.4, 1737.4", "1738.0, 1738.0, 1738.0"),
        ("Date__(UT)", "Date__(TT)"),
        ("Azimuth_(a-app)", "wrong"),
    ],
)
def test_bad_headers(before, after, request_model):
    data = payload()
    assert before in data["result"]
    data["result"] = data["result"].replace(before, after)
    with pytest.raises(EphemerisError):
        parse_response(json.dumps(data).encode(), 10, request_model)


@pytest.mark.parametrize("values", ["NaN,0", "360,0", "-1,0", "0,91", "0,-91", "inf,0", "bad,0"])
def test_invalid_numeric_values(values, request_model):
    data = payload()
    header, rest = data["result"].split("$$SOE")
    table, tail = rest.split("$$EOE")
    first = table.strip().splitlines()[0].split(",")
    first[3:5] = values.split(",")
    data["result"] = header + "$$SOE\n" + ",".join(first) + "\n$$EOE" + tail
    with pytest.raises(EphemerisError):
        parse_response(json.dumps(data).encode(), 10, request_model)


def test_missing_value_null_and_aliases(request_model):
    data = payload()
    header, rest = data["result"].split("$$SOE")
    table, tail = rest.split("$$EOE")
    first = table.strip().splitlines()[0].split(",")
    first[3] = "n.a."
    header = (
        header.replace("Azimuth_(a-app)", "Azi_(a-app)")
        .replace("Elevation_(a-app)", "Elev_(a-app)")
        .replace("MEAN_ME", "MOON_ME")
    )
    data["result"] = header + "$$SOE\n" + ",".join(first) + "\n$$EOE" + tail
    assert list(parse_response(json.dumps(data).encode(), 10, request_model).values()) == [None]


def test_reordered_columns_use_labels(request_model):
    data = payload()
    lines = data["result"].splitlines()
    inside = False
    for i, line in enumerate(lines):
        if "Date__(UT)" in line or (inside and line.strip() and line != "$$EOE"):
            fields = line.split(",")
            fields[3], fields[4] = fields[4], fields[3]
            lines[i] = ",".join(fields)
        if line == "$$SOE":
            inside = True
        if line == "$$EOE":
            inside = False
    data["result"] = "\n".join(lines)
    original = parse_response(json.dumps(payload()).encode(), 10, request_model)
    assert parse_response(json.dumps(data).encode(), 10, request_model) == original


@pytest.mark.parametrize("mode", ["duplicate", "truncated", "empty", "signature", "error"])
def test_malformed_rows(mode, request_model):
    data = payload()
    header, rest = data["result"].split("$$SOE")
    table, tail = rest.split("$$EOE")
    first = table.strip().splitlines()[0]
    if mode == "duplicate":
        data["result"] = header + "$$SOE\n" + first + "\n" + first + "\n$$EOE" + tail
    elif mode == "truncated":
        data["result"] = header + "$$SOE\n" + first.split(",")[0] + "\n$$EOE" + tail
    elif mode == "empty":
        data["result"] = header + "$$SOE\n$$EOE" + tail
    elif mode == "signature":
        data["signature"]["version"] = "99"
    else:
        data["error"] = "synthetic test error"
    with pytest.raises(EphemerisError):
        parse_response(json.dumps(data).encode(), 10, request_model)
