import asyncio
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

import httpx
from celestial_engine.horizons_client import legacy_get
from app.catalog import SITES
from app.metadata import iso, metadata
from app.science.grid import lookup

URL = 'https://ssd.jpl.nasa.gov/api/horizons.api'
PARSER_VERSION = 'horizons-az-el-v1'


class SourceUnavailable(Exception):
    pass


def sky(az, el):
    if not math.isfinite(az) or not math.isfinite(el) or not 0 <= az < 360 or not -90 <= el <= 90:
        raise ValueError('Invalid azimuth/elevation range')
    a, e = math.radians(az), math.radians(el)
    return dict(az_deg=az, el_deg=el, east=math.cos(e)*math.sin(a), north=math.cos(e)*math.cos(a), up=math.sin(e), status='KNOWN')


def parse_response(raw, target, site):
    body = json.loads(raw)
    if body.get('error'):
        raise ValueError('Horizons returned an error')
    text = body.get('result', '')
    if '$$SOE' not in text or '$$EOE' not in text:
        raise ValueError('Missing Horizons table delimiters')
    header, rest = text.split('$$SOE', 1)
    table = rest.split('$$EOE', 1)[0]
    target_name = {10: 'Sun', 399: 'Earth'}[int(target)]
    if not re.search(rf'Target body name:\s*{target_name}\s*\({target}\)', header):
        raise ValueError('Target header mismatch')
    if not re.search(r'Center body name:\s*Moon\s*\(301\)', header) or 'AIRLESS' not in header:
        raise ValueError('Not a lunar airless observer table')
    match = re.search(r'Center geodetic\s*:\s*([\d.eE+-]+),\s*([\d.eE+-]+),\s*([\d.eE+-]+)', header)
    if not match:
        raise ValueError('Missing observer coordinates')
    lon, lat, height = map(float, match.groups())
    delta_lon = abs((lon - site['lon_east_deg'] + 180) % 360 - 180)
    if delta_lon > 1e-4 or abs(lat-site['lat_deg']) > 1e-4 or abs(height-site['reference_height_km']) > 1e-4:
        raise ValueError('Observer coordinates/height mismatch')
    headings = next((next(csv.reader([line])) for line in header.splitlines() if 'Date__(UT)' in line and 'Azi_' in line), None)
    if not headings:
        raise ValueError('Missing UT azimuth/elevation column labels')
    headings = [x.strip() for x in headings]
    az_index = next((i for i, x in enumerate(headings) if x == 'Azi_(a-app)'), None)
    el_index = next((i for i, x in enumerate(headings) if x == 'Elev_(a-app)'), None)
    if az_index is None or el_index is None:
        raise ValueError('Unsupported angle convention')
    records = {}
    previous = None
    for row in csv.reader(table.strip().splitlines()):
        timestamp = row[0].strip()
        # Horizons can omit seconds even when TIME_DIGITS requests them.
        time_format = '%Y-%b-%d %H:%M' if timestamp.count(':') == 1 else '%Y-%b-%d %H:%M:%S'
        stamp = datetime.strptime(timestamp, time_format).replace(tzinfo=timezone.utc)
        if previous is not None and stamp <= previous:
            raise ValueError('Nonmonotonic or duplicate UTC records')
        previous = stamp
        if row[az_index].strip() in ('n.a.', '') or row[el_index].strip() in ('n.a.', ''):
            position = None
        else:
            position = sky(float(row[az_index]), float(row[el_index]))
        records[iso(stamp)] = position
    if not records:
        raise ValueError('Empty observer table')
    return records


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent, delete=False) as stream:
        stream.write(content)
        temp = stream.name
    os.replace(temp, path)


class Horizons:
    def __init__(self, root=None):
        self.root = Path(root or os.getenv('WISPR_DATA_DIR', 'data')) / 'raw'
        self.gate = asyncio.Semaphore(2)
        self.live = None
        self.last_error = None

    async def target(self, target, site, request):
        quote = lambda value: "'" + str(value) + "'"
        params = dict(format='json', COMMAND=quote(target), MAKE_EPHEM="'YES'", OBJ_DATA="'NO'",
            EPHEM_TYPE="'OBSERVER'", CENTER="'coord@301'", COORD_TYPE="'GEODETIC'",
            SITE_COORD=quote(f"{site['lon_east_deg']},{site['lat_deg']},{site['reference_height_km']}"),
            START_TIME=quote(request.start_utc.strftime('%Y-%m-%d %H:%M')),
            STOP_TIME=quote(request.end_utc.strftime('%Y-%m-%d %H:%M')), STEP_SIZE=quote(f'{request.step_minutes} min'),
            TIME_TYPE="'UT'", TIME_ZONE="'+00:00'", QUANTITIES="'4'", APPARENT="'AIRLESS'",
            CSV_FORMAT="'YES'", ANG_FORMAT="'DEG'", TIME_DIGITS="'SECONDS'")
        key = hashlib.sha256(json.dumps(dict(params=params, parser=PARSER_VERSION), sort_keys=True).encode()).hexdigest()
        raw_path, meta_path = self.root / f'{key}.json', self.root / f'{key}.meta.json'
        cache = None
        try:
            raw = raw_path.read_bytes()
            meta = json.loads(meta_path.read_text())
            if meta['params'] == params and meta['parser_version'] == PARSER_VERSION and hashlib.sha256(raw).hexdigest() == meta['raw_sha256']:
                cache = (parse_response(raw, target, site), meta, 'NASA_JPL_VERIFIED_CACHE')
        except (OSError, ValueError, KeyError, IndexError, StopIteration):
            pass
        # Exact verified cached requests are reused to avoid repeatedly querying JPL.
        if cache:
            return cache
        if request.source_preference == 'VERIFIED_CACHE_ONLY':
            raise SourceUnavailable('No verified cache for these exact coordinates, interval and sampling settings')
        try:
            async with self.gate:
                response = await asyncio.to_thread(legacy_get, params)
            raw = response.content
            records = parse_response(raw, target, site)
            meta = dict(params=params, parser_version=PARSER_VERSION, raw_sha256=hashlib.sha256(raw).hexdigest(),
                fetched_at_utc=iso(datetime.now(timezone.utc)), source_url=str(response.url))
            atomic_write(raw_path, raw)
            atomic_write(meta_path, json.dumps(meta, indent=2).encode())
            self.live, self.last_error = True, None
            return records, meta, 'NASA_JPL_LIVE'
        except (httpx.HTTPError, ValueError, OSError, IndexError, StopIteration) as exc:
            self.live, self.last_error = False, type(exc).__name__
            raise SourceUnavailable(f'JPL retrieval/validation failed ({type(exc).__name__}); no verified cache') from exc

    async def ephemeris(self, request):
        if request.site_id in SITES:
            site = dict(SITES[request.site_id])
        elif request.site_id and request.site_id.startswith('SP1KM:'):
            c = lookup(request.site_id)
            site = dict(site_id=c['cell_id'], lat_deg=c['center_lat_deg'], lon_east_deg=c['center_lon_east_deg'])
        elif request.site_id:
            raise ValueError('Unknown site ID')
        else:
            site = dict(lat_deg=request.lat_deg, lon_east_deg=request.lon_east_deg)
        site['reference_height_km'] = float(os.getenv('HORIZONS_REFERENCE_HEIGHT_KM', '0'))
        if not math.isfinite(site['reference_height_km']):
            raise ValueError('Invalid reference height configuration')
        sun, sm, ss = await self.target(10, site, request)
        earth, em, es = await self.target(399, site, request)
        expected = []
        t = request.start_utc
        while t <= request.end_utc:
            expected.append(iso(t))
            t += timedelta(minutes=request.step_minutes)
        records = []
        for stamp in expected:
            s, e = sun.get(stamp), earth.get(stamp)
            known = s is not None and e is not None
            records.append(dict(timestamp_utc=stamp, sun=s, earth=e, status='KNOWN' if known else 'UNKNOWN',
                gap_reason=None if known else 'MISSING_OR_INVALID_TARGET_OBSERVATION'))
        missing = [dict(start_utc=r['timestamp_utc'], reason=r['gap_reason']) for r in records if r['status'] == 'UNKNOWN']
        provenance = dict(dataset_ids=['JPL Horizons'], source_urls=[sm['source_url'], em['source_url']],
            request_params={'sun': sm['params'], 'earth': em['params']}, raw_sha256=[sm['raw_sha256'], em['raw_sha256']],
            coordinate_frame='Lunar MEAN_ME; JPL reference sphere; local ENU', sample_step_minutes=request.step_minutes,
            fetched_at_utc=[sm['fetched_at_utc'], em['fetched_at_utc']], reference_height_km=site['reference_height_km'],
            observer_height_above_ground_m=request.observer_height_m, observer_height_applied_to_horizons=False,
            target_timestamp_sets_match=set(sun) == set(earth), axes='east, north, up; azimuth clockwise from north; input degrees')
        source = ss if ss == es else 'MIXED_VERIFIED'
        return dict(site=site, records=records, missing_intervals=missing, observed_start_utc=records[0]['timestamp_utc'],
            observed_end_utc=records[-1]['timestamp_utc'], step_minutes=request.step_minutes,
            **metadata(source, 'GEOMETRIC_IDEAL', 'SOURCE_BACKED' if not missing else 'PARTIAL', provenance))
