"""Test-only global arrays; the live adapter validates the real source hash."""
from types import SimpleNamespace
import numpy as np
import pytest
from app.regions import terrain_mesh as tm
from lunar_global import sources,features

@pytest.fixture
def overview(tmp_path,monkeypatch):
    directory=tmp_path/'source_products/lola';directory.mkdir(parents=True)
    (directory/'source.json').write_text('{}')
    monkeypatch.setenv('WISPR_GLOBAL_ROOT',str(tmp_path))
    monkeypatch.setattr(tm,'sources',lambda:[])
    product=SimpleNamespace(product_identifier='LDEM_4',coordinate_frame='MOON_ME_DE421',status='VERIFIED',
        spatial_resolution_m=7580.84,source_id='TEST_ONLY',source_checksum='test',canonical_url='test',vertical_reference='test')
    monkeypatch.setattr(sources.SourceProduct,'model_validate_json',lambda value:product)
    z=np.full((720,1440),123.5)
    monkeypatch.setattr(features,'native_terrain',lambda path,source:(z,z,z))
    return {'region_id':'TEST:OVERVIEW','coordinate_frame':'MOON_ME_DE421','geometry':{'type':'Polygon',
        'coordinates':[[[341.4,-83.03],[341.6,-83.03],[341.6,-83.07],[341.4,-83.07],[341.4,-83.03]]]}}

def test_overview_requires_opt_in_and_discloses_resolution(overview):
    with pytest.raises(ValueError,match='No high-resolution'):tm.extract(overview,'preview')
    result=tm.extract(overview,'preview','inside',True)
    assert result['manifest']['data_quality']=='COARSE_OVERVIEW_ONLY'
    assert result['manifest']['native_spacing_m'] is None
    assert result['manifest']['native_angular_spacing_deg']==.25
    assert result['manifest']['coverage_fraction']==pytest.approx(1)
    assert all(v[2]==pytest.approx(123.5) for v in result['vertices'])

def test_overview_rejects_native_and_unsupported_scopes(overview):
    with pytest.raises(ValueError,match='Native regional'):tm.extract(overview,'native','inside',True)
    with pytest.raises(ValueError,match='Inside polygon only'):tm.extract(overview,'preview','global',True)

def test_overview_never_hides_corrupt_source(overview,monkeypatch):
    def corrupt(*args):raise ValueError('Source checksum mismatch')
    monkeypatch.setattr(features,'native_terrain',corrupt)
    with pytest.raises(ValueError,match='failed integrity'):tm.extract(overview,'preview','inside',True)
