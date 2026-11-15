import io
import json
import zipfile
from unittest.mock import Mock
import pytest
from app.regions import research_report as rr

@pytest.fixture
def report():
    return {'region':{'region_id':'test-region','latitude_deg':-88.,'longitude_deg':12.,'area_m2':1000000.,'geometry':{'type':'Polygon','coordinates':[[[12,-88],[12.01,-88],[12.01,-87.99],[12,-87.99],[12,-88]]]}},
            'context':{'measurement_support':{'source_resolution_m':5},'available_datasets':[{'source_id':'verified-source','status':'VERIFIED','source_checksum':'abc','canonical_url':'https://example.org/data'}]},
            'tools':[{'tool':'calculate_elevation_statistics','status':'COMPLETE','data':{'area_weighted_mean':100.,'minimum':90.,'maximum':110.,'unit':'m','coverage_fraction':1.,'source_id':'verified-source'}}],
            'input':{'mission':None},'limitations':['Terrain occlusion is unknown.']}

def test_unknowns_are_not_zero_and_measured_values_are_preserved(report):
    cards={c['id']:c for c in rr.facts(report)}
    assert cards['elevation']['value']=='100 m'
    assert cards['craters']['value']=='Not measured'
    assert cards['sun']['value']=='Not measured'
    assert 'Unknown does not mean zero' in cards['craters']['note']

def test_report_bundle_has_portable_image_and_original_evidence(report,monkeypatch):
    report['research']=rr.build(report)
    job={'job_id':'j1','result_sha256':'hash','status':'COMPLETE','result':report}
    monkeypatch.setattr(rr.store,'get',lambda *args:job)
    response=rr.download_bundle('j1')
    with zipfile.ZipFile(io.BytesIO(response.body)) as z:
        assert set(z.namelist())=={'report.md','summary.svg','evidence.json','boundary.geojson'}
        md=z.read('report.md').decode()
        assert '(summary.svg)' in md and '100 m' in md and 'Not measured' in md
        assert json.loads(z.read('evidence.json'))==report
        assert 'not a terrain photograph' in z.read('summary.svg').decode()

def test_visibility_unknown_fraction_is_disclosed(report):
    report['tools'].append({'tool':'calculate_visibility_windows','status':'COMPLETE','data':{'metrics':{'sun_visible_fraction':.5},'unknown_fraction':.25}})
    sun=next(c for c in rr.facts(report) if c['id']=='sun')
    assert sun['value']=='50% of interval'
    assert '25%' in sun['note'] and 'Representative point' in sun['note']

def test_image_escapes_report_values(report):
    cards=rr.facts(report);cards[0]['value']='<script>alert(1)</script>'
    image=rr.image_svg(report,cards)
    assert '<script>' not in image and '&lt;script&gt;' in image

def test_incomplete_job_cannot_download(monkeypatch):
    monkeypatch.setattr(rr.store,'get',lambda *args:{'status':'RUNNING'})
    with pytest.raises(Exception) as exc:rr.download_bundle('j1')
    assert exc.value.status_code==409


def test_unavailable_ai_explanation_is_retried(monkeypatch):
    from app.regions import agent
    old={'status':'COMPLETE','result':{'tools':[],'research':{'ai':{'status':'UNAVAILABLE'}}}}
    monkeypatch.setattr(agent,'context',lambda r:{'region':{'region_id':'r'},'source_fingerprint':'source'})
    monkeypatch.setattr(agent.store,'get',lambda kind,key: old if kind=='job' else {})
    monkeypatch.setattr(agent.store,'put',Mock())
    gate=Mock();gate.acquire.return_value=True
    monkeypatch.setattr(agent,'GATE',gate)
    pool=Mock();monkeypatch.setattr(agent,'POOL',pool)
    result=agent.launch('r',agent.AnalyzeRequest(use_report_ai=True))
    assert result['status']=='QUEUED' and not result['cache_hit']
    pool.submit.assert_called_once()
