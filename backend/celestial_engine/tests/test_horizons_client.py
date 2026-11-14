import httpx
import pytest

from celestial_engine.horizons_client import (
    HorizonsClient,
    SourceUnavailable,
    parameters,
)


def test_parameters(request_model):
    p = parameters(10, request_model)
    assert p["SITE_COORD"] == "'45.0,-89.0,0.0'"
    assert p["CENTER"] == "'coord@301'"
    assert p["COMMAND"] == "'10'"
    assert parameters(399, request_model)["COMMAND"] == "'399'"
    assert p["TIME_TYPE"] == "'UT'" and p["QUANTITIES"] == "'4'"
    assert p["ELEV_CUT"] == "'-90'" and p["TIME_DIGITS"] == "'SECONDS'"


def test_cache_repeatability_and_offline(engine, request_model):
    first = engine.ephemeris(request_model)
    engine.client.offline = True
    second = engine.ephemeris(request_model)
    assert first.records == second.records
    assert second.metadata["queries"]["sun"]["delivery"] == "VERIFIED_CACHE"


def test_tampered_cache_rejected(engine, request_model):
    engine.ephemeris(request_model)
    for path in engine.client.cache.root.glob("*.json"):
        path.write_text('{"raw":"changed","metadata":{}}')
    engine.client.offline = True
    with pytest.raises(SourceUnavailable):
        engine.ephemeris(request_model)


@pytest.mark.parametrize("kind", ["timeout", "network", "429", "503", "400", "payload"])
def test_failures_bounded(tmp_path, request_model, kind):
    calls = []

    def fail(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("test only")
        if kind == "network":
            raise httpx.ConnectError("test only")
        if kind == "payload":
            return httpx.Response(200, json={"error": "test query rejected"})
        return httpx.Response(int(kind), headers={"Retry-After": "0"})

    client = HorizonsClient(tmp_path, transport=httpx.MockTransport(fail), backoff=0)
    with pytest.raises(SourceUnavailable):
        client.target(10, request_model)
    assert len(calls) == (1 if kind in ("400", "payload") else 3)
    if kind == "payload":
        assert len(list((tmp_path / "rejected").glob("*.json"))) == 1


def test_retry_recovers(tmp_path, request_model, recorded_transport):
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return recorded_transport.handle_request(request)

    records, meta = HorizonsClient(
        tmp_path, transport=httpx.MockTransport(respond), backoff=0
    ).target(10, request_model)
    assert len(calls) == 2 and len(records) == 169
    assert meta["delivery"] == "LIVE"  # Transport delivery label; fixture use is established above.


def test_concurrent_clients_coalesce(tmp_path, request_model, recorded_transport):
    from concurrent.futures import ThreadPoolExecutor

    calls = []

    def respond(request):
        calls.append(request)
        return recorded_transport.handle_request(request)

    def run(_):
        return HorizonsClient(tmp_path, transport=httpx.MockTransport(respond)).target(
            10, request_model
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert len(calls) == 1
    assert all(result[0] == results[0][0] for result in results)
