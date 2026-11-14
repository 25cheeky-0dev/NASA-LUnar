import json
from pathlib import Path

import httpx
import pytest

from celestial_engine.__main__ import SAMPLE
from celestial_engine.celestial_service import CelestialService
from celestial_engine.horizons_client import HorizonsClient
from celestial_engine.schemas import EphemerisRequest

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def request_model():
    return EphemerisRequest(**SAMPLE)


@pytest.fixture
def recorded_transport():
    def respond(request):
        name = "sun" if request.url.params["COMMAND"] == "'10'" else "earth"
        return httpx.Response(200, content=(FIXTURES / f"{name}.json").read_bytes())

    return httpx.MockTransport(respond)


@pytest.fixture
def engine(tmp_path, recorded_transport):
    # Authentic recorded NASA fixtures; mocked HTTP is explicitly not a live test.
    return CelestialService(HorizonsClient(tmp_path, transport=recorded_transport, backoff=0))


def payload(name="sun"):
    return json.loads((FIXTURES / f"{name}.json").read_bytes())
