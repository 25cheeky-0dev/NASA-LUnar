"""Bounded synchronous NASA client; one upstream request at a time per process."""

import logging
import os
import ssl
import threading
import time
from datetime import UTC, datetime

import httpx
import truststore

from .cache import QueryCache, atomic_write, digest
from .data_validation import EphemerisError
from .ephemeris_parser import PARSER_VERSION, parse_response

URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
UPSTREAM_LOCK = threading.Lock()
LOG = logging.getLogger(__name__)
DEFAULT_USER_AGENT = (
    "WISPR-Celestial/1.0 (+https://github.com/25cheeky-0dev/LUNA---MOON---NASA-HACKATHON)"
)


class SourceUnavailable(RuntimeError):
    pass


def parameters(target, request):
    if target not in (10, 399):
        raise ValueError("Supported targets are Sun 10 and Earth 399")
    values = dict(
        COMMAND=target,
        EPHEM_TYPE="OBSERVER",
        CENTER="coord@301",
        COORD_TYPE="GEODETIC",
        SITE_COORD=f"{request.longitude_east_deg},{request.latitude_deg},{request.altitude_km}",
        START_TIME=request.start_utc.strftime("%Y-%m-%d %H:%M"),
        STOP_TIME=request.end_utc.strftime("%Y-%m-%d %H:%M"),
        STEP_SIZE=f"{request.step_minutes} min",
        QUANTITIES="4",
        TIME_TYPE="UT",
        TIME_ZONE="+00:00",
        CSV_FORMAT="YES",
        MAKE_EPHEM="YES",
        OBJ_DATA="NO",
        APPARENT="AIRLESS",
        ANG_FORMAT="DEG",
        TIME_DIGITS="SECONDS",
        ELEV_CUT="-90",
        SKIP_DAYLT="NO",
        EXTRA_PREC="YES",
    )
    return {"format": "json", **{key: f"'{value}'" for key, value in values.items()}}


class HorizonsClient:
    def __init__(self, cache_dir=None, *, transport=None, attempts=3, backoff=1.0, offline=False):
        if not 1 <= attempts <= 5 or not 0 <= backoff <= 60:
            raise ValueError("Invalid retry configuration")
        self.cache = QueryCache(cache_dir or os.getenv("CELESTIAL_CACHE_DIR", "data/celestial"))
        self.transport, self.attempts, self.backoff, self.offline = (
            transport,
            attempts,
            backoff,
            offline,
        )

    def target(self, target, request):
        params = parameters(target, request)
        # The lock also coalesces identical requests after the first cache write.
        with UPSTREAM_LOCK:
            entry = self.cache.get(params)
            if entry:
                raw, meta = entry
                try:
                    if meta.get("parser_version") != PARSER_VERSION:
                        raise EphemerisError("Cached parser version changed")
                    records = parse_response(raw, target, request)
                    return records, dict(meta, delivery="VERIFIED_CACHE")
                except EphemerisError:
                    LOG.warning("Discarding invalid celestial cache entry")
            if self.offline:
                raise SourceUnavailable("Exact validated cache unavailable; network disabled")
            context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            with httpx.Client(
                timeout=httpx.Timeout(45, connect=10),
                verify=context,
                transport=self.transport,
                headers={"User-Agent": os.getenv("CELESTIAL_USER_AGENT", DEFAULT_USER_AGENT)},
            ) as client:
                for attempt in range(self.attempts):
                    try:
                        LOG.info(
                            "Horizons target=%s attempt=%s query=%s",
                            target,
                            attempt + 1,
                            self.cache.key(params),
                        )
                        response = client.get(URL, params=params)
                        response.raise_for_status()
                        raw = response.content
                        try:
                            records = parse_response(raw, target, request)
                        except EphemerisError:
                            atomic_write(
                                self.cache.root / "rejected" / f"{digest(raw)}.json",
                                raw,
                            )
                            raise
                        meta = dict(
                            query_parameters=params,
                            source_url=str(response.url),
                            raw_sha256=digest(raw),
                            retrieved_at_utc=datetime.now(UTC).isoformat(),
                            parser_version=PARSER_VERSION,
                            api_signature=response.json()["signature"],
                            ephemeris_header=response.json()["result"].split("$$SOE")[0],
                        )
                        self.cache.put(params, raw, meta)
                        return records, dict(meta, delivery="LIVE")
                    except EphemerisError as exc:
                        raise SourceUnavailable(str(exc)) from exc
                    except httpx.HTTPError as exc:
                        retryable = not isinstance(
                            exc, httpx.HTTPStatusError
                        ) or exc.response.status_code in (429, 500, 502, 503, 504)
                        if not retryable or attempt + 1 == self.attempts:
                            raise SourceUnavailable(
                                f"NASA retrieval failed ({type(exc).__name__}); no substitute data"
                            ) from exc
                        delay = min(60, self.backoff * 2**attempt)
                        if isinstance(exc, httpx.HTTPStatusError):
                            try:
                                delay = max(
                                    delay,
                                    min(
                                        60,
                                        float(exc.response.headers.get("Retry-After", "0")),
                                    ),
                                )
                            except ValueError:
                                pass
                        time.sleep(delay)
        raise SourceUnavailable("NASA retrieval exhausted")


def legacy_get(params):
    """Share the process-wide NASA gate with the existing async WISPR provider."""
    with UPSTREAM_LOCK:
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with httpx.Client(
            timeout=35,
            verify=context,
            headers={"User-Agent": os.getenv("CELESTIAL_USER_AGENT", DEFAULT_USER_AGENT)},
        ) as client:
            response = client.get(URL, params=params)
            response.raise_for_status()
            return response
