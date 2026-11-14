import math
import pytest
from app.catalog import SITES
from app.science.grid import project,unproject,neighborhood,lookup,cell_at,PROJECTION
from app.science.features import feature_space


@pytest.mark.parametrize('lat,lon',[(-90,0),(-89,0),(-89,360),(-89,-180),(-89,180),(-89,222.51),(-89.9,359.99)])
def test_lunar_projection_round_trip(lat,lon):
    x,y=project(lat,lon)
    la,lo=unproject(x,y)
    assert abs(la-lat)<1e-9
    if lat != -90:
        assert abs((lo-lon+180)%360-180)<1e-8
    assert '+R=1737400' in PROJECTION['wkt_or_proj']
    assert '3031' not in PROJECTION['wkt_or_proj']


@pytest.mark.parametrize('site_id',['R01','R04'])
def test_nine_stable_cells_without_astronomy(site_id):
    g=neighborhood(site_id)
    assert len(g['cells'])==9
    assert len({c['cell_id'] for c in g['cells']})==9
    assert g['center_cell_id']==cell_at(SITES[site_id]['lat_deg'],SITES[site_id]['lon_east_deg'])['cell_id']
    for c in g['cells']:
        assert lookup(c['cell_id'])==c
        assert c['ephemeris_status']=='UNEVALUATED'
        assert len(c['boundary_lonlat_east'])==5
        corners=[project(lat,lon) for lon,lat in c['boundary_lonlat_east']]
        assert math.dist(corners[0],corners[1])==pytest.approx(1000,abs=1e-6)


def test_missing_features_never_imputed_and_reference_separate():
    s=dict(site_id='R01',scenario_id='time-a',arrival_utc='2026-11-20T00:00:00Z',end_utc='2026-11-21T00:00:00Z',horizon_model='GEOMETRIC',observer_height_m=1,
        known_fraction=.5,unknown_fraction=.5,longest_shared_minutes=60,data_quality='PARTIAL',source_type='SYNTHETIC_TEST_ONLY',calculation_mode='GEOMETRIC_IDEAL',provenance={},metrics={'sun_visible_fraction':.3})
    f=feature_space(s)
    assert all(p['values']==[None]*6 for p in f['points'])
    ref=f['reference_points'][0]
    assert ref['values'][0] is None
    assert ref['values'][3]==1
    assert ref['values'][5] is None
    assert not ref['similarity_eligible']
    assert ref['does_not_evaluate_cell_center']
    s['scenario_id']='time-b'
    assert feature_space(s)['reference_points'][0]['scenario_id']!=ref['scenario_id']
