import asyncio
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import pytest
from app.providers.horizons import parse_response,sky,Horizons,SourceUnavailable,PARSER_VERSION
from app.schemas import EphemerisRequest

SITE=dict(lon_east_deg=222.51,lat_deg=-89.4632,reference_height_km=0)


def synthetic_table(rows=None):
    # SYNTHETIC TEST DATA — NOT NASA MEASUREMENTS.
    return json.dumps({'result':'''Target body name: Sun (10)
Center body name: Moon (301)
Center geodetic : 222.51, -89.4632, 0.0
Atmos refraction: NO (AIRLESS)
 Date__(UT)__HR:MN:SS, , ,Azi_(a-app), Elev_(a-app),
$$SOE
'''+(rows or '2026-Nov-20 00:00:00,*,i,191.0,1.0,\n2026-Nov-20 00:05:00,*,i,190.9,1.1,')+'\n$$EOE'})


def test_actual_nasa_response_when_fixture_present():
    path=Path(__file__).parent/'fixtures'/'jpl_sun_R01_20261120.json'
    raw=path.read_bytes()
    records=parse_response(raw,10,SITE)
    assert records['2026-11-20T00:00:00Z']['el_deg']==1.017911
    assert records['2026-11-20T00:05:00Z']['az_deg']==191.042390


def test_actual_earth_response():
    path=Path(__file__).parent/'fixtures'/'jpl_short_earth.json'
    records=parse_response(path.read_bytes(),399,SITE)
    assert records['2026-11-20T00:00:00Z']['el_deg']==2.824754
    assert records['2026-11-20T00:05:00Z']['az_deg']==130.274592


def test_verified_cache_replays_without_network_and_rejects_tampering(tmp_path):
    provider=Horizons(tmp_path)
    provider.root.mkdir()
    fixtures=Path(__file__).parent/'fixtures'
    for name in ('sun','earth'):
        meta=json.loads((fixtures/f'jpl_short_{name}.meta.json').read_text())
        key=hashlib.sha256(json.dumps(dict(params=meta['params'],parser=PARSER_VERSION),sort_keys=True).encode()).hexdigest()
        (provider.root/f'{key}.json').write_bytes((fixtures/f'jpl_short_{name}.json').read_bytes())
        (provider.root/f'{key}.meta.json').write_text(json.dumps(meta))
    request=EphemerisRequest(site_id='R01',start_utc='2026-11-20T00:00:00Z',end_utc='2026-11-20T00:10:00Z',source_preference='VERIFIED_CACHE_ONLY')
    result=asyncio.run(provider.ephemeris(request))
    assert result['source_type']=='NASA_JPL_VERIFIED_CACHE'
    assert len(result['records'])==3
    assert not result['missing_intervals']
    assert provider.live is None
    for raw in provider.root.glob('*.json'):
        if not raw.name.endswith('.meta.json'):
            raw.write_text('tampered')
    with pytest.raises(SourceUnavailable):
        asyncio.run(provider.ephemeris(request))


def test_timestamp_mismatch_is_unknown_not_row_index_join(tmp_path):
    provider=Horizons(tmp_path)
    async def target(target_id,site,request):
        rows={'2026-11-20T00:00:00Z':sky(180,1)}
        rows['2026-11-20T00:05:00Z' if target_id==10 else '2026-11-20T00:10:00Z']=sky(180,2)
        return rows,dict(params={},raw_sha256='synthetic-test-only',source_url='SYNTHETIC_TEST_ONLY',fetched_at_utc='2026-11-14T00:00:00Z'),'SYNTHETIC_TEST_ONLY'
    provider.target=target
    request=EphemerisRequest(site_id='R01',start_utc='2026-11-20T00:00:00Z',end_utc='2026-11-20T00:10:00Z')
    result=asyncio.run(provider.ephemeris(request))
    assert not result['provenance']['target_timestamp_sets_match']
    assert result['records'][1]['earth'] is None
    assert result['records'][2]['sun'] is None
    assert result['records'][1]['status']=='UNKNOWN'


@pytest.mark.parametrize('change',[
    lambda s:s.replace('Sun (10)','Earth (399)'),
    lambda s:s.replace('Moon (301)','Earth (399)'),
    lambda s:s.replace('222.51','222.52'),
    lambda s:s.replace('$$SOE','SOE'),
    lambda s:s.replace('Azi_(a-app)','wrong'),
    lambda s:s.replace('191.0,1.0','191.0,91.0'),
    lambda s:s.replace('190.9,1.1','NaN,1.1'),
    lambda s:s.replace('00:05:00','00:00:00'),
])
def test_malformed_or_mismatched_response_rejected(change):
    with pytest.raises(ValueError):
        parse_response(change(synthetic_table()),10,SITE)


def test_unavailable_angle_remains_null():
    data=parse_response(synthetic_table('2026-Nov-20 00:00:00, , ,n.a.,n.a.,'),10,SITE)
    assert next(iter(data.values())) is None


def test_scientific_notation_reference_height():
    raw=synthetic_table().replace('-89.4632, 0.0','-89.4632, 1.92896E-13')
    assert len(parse_response(raw,10,SITE))==2


def test_enu_axes_and_unit_length():
    p=sky(90,0)
    assert p['east']==pytest.approx(1)
    assert p['north']==pytest.approx(0,abs=1e-12)
    p=sky(132,-7)
    assert sum(p[a]**2 for a in ('east','north','up'))==pytest.approx(1)


def test_tampered_cache_never_used(tmp_path):
    provider=Horizons(tmp_path)
    provider.root.mkdir()
    # Arbitrary cached files without checked metadata cannot satisfy a query.
    (provider.root/'bad.json').write_text(synthetic_table())
    request=EphemerisRequest(site_id='R01',start_utc='2026-11-20T00:00:00Z',end_utc='2026-11-20T00:10:00Z',source_preference='VERIFIED_CACHE_ONLY')
    with pytest.raises(SourceUnavailable):
        asyncio.run(provider.ephemeris(request))


def test_minute_precision_timestamps():
    raw = synthetic_table().replace('00:00:00,', '00:00,').replace('00:05:00,', '00:05,')
    records = parse_response(raw, 10, SITE)
    assert list(records) == ['2026-11-20T00:00:00Z', '2026-11-20T00:05:00Z']
    assert records['2026-11-20T00:05:00Z']['el_deg'] == 1.1
