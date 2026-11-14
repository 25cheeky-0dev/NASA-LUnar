import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from app.schemas import RecoveryRequest
from app.metadata import iso,metadata
from app.science.recovery import recover_mission,rank_candidates


def fake_analysis(statuses,seen):
    async def analyze(site,start,end,request):
        seen.append((site,start,end))
        day=(start-request.original_arrival_utc).days
        status=statuses.get((site,day),'FAILS')
        window=dict(start_utc=iso(start),end_utc=iso(start+timedelta(hours=3)),duration_minutes=180,kind='BOTH',estimate_status='MODEL_ESTIMATE',boundary_uncertainty_seconds=300,model='GEOMETRIC_IDEAL')
        return dict(scenario_id=site+iso(start),site_id=site,arrival_utc=iso(start),end_utc=iso(end),horizon_model=request.horizon_model,
            qualifying_status=status,earliest_qualifying_window=window if status=='QUALIFIES' else None,
            known_fraction=0 if status=='UNKNOWN' else 1,reason_codes=[] if status=='QUALIFIES' else [status],**metadata('SYNTHETIC_TEST_ONLY'))
    return analyze


def recover(statuses,**kwargs):
    seen=[]
    request=RecoveryRequest(original_arrival_utc='2026-11-20T00:00:00Z',original_site_id='R01',study_duration_hours=24,**kwargs)
    result=asyncio.run(recover_mission(request,fake_analysis(statuses,seen)))
    return result,seen


@pytest.mark.parametrize('statuses,outcome,site',[
    ({('R01',7):'QUALIFIES',('R04',7):'QUALIFIES'},'KEEP_SITE_AFTER_DELAY','R01'),
    ({('R04',7):'QUALIFIES'},'SWITCH_SITE_AFTER_DELAY','R04'),
    ({},'NO_QUALIFYING_OPTION_WITHIN_SEARCH',None),
    ({('R01',7):'UNKNOWN'},'INSUFFICIENT_DATA',None),
    ({('R01',7):'UNKNOWN',('R04',7):'QUALIFIES'},'INSUFFICIENT_DATA',None),
])
def test_outcomes(statuses,outcome,site):
    result,seen=recover(statuses)
    assert result['recommended_outcome']==outcome
    assert result['recommended_site_id']==site
    assert len(seen)==4
    assert not result['future_scenarios']


def test_reverse_original_site_switch():
    seen=[]
    request=RecoveryRequest(original_site_id='R04',original_arrival_utc='2026-11-20T00:00:00Z',study_duration_hours=24)
    result=asyncio.run(recover_mission(request,fake_analysis({('R01',7):'QUALIFIES'},seen)))
    assert result['recommended_site_id']=='R01'
    assert result['recommended_outcome']=='SWITCH_SITE_AFTER_DELAY'


@pytest.mark.parametrize('stamp',['2024-02-27T23:00:00Z','2026-12-29T00:00:00Z','2026-01-29T01:00:00Z'])
def test_exact_168_hours_across_calendar(stamp):
    request=RecoveryRequest(original_site_id='R01',original_arrival_utc=stamp,study_duration_hours=48)
    seen=[]
    result=asyncio.run(recover_mission(request,fake_analysis({},seen)))
    assert seen[2][1]-seen[0][1]==timedelta(hours=168)
    assert all(end-start==timedelta(hours=48) for _,start,end in seen)
    assert [s[0] for s in seen]==['R01','R04','R01','R04']


def test_future_search_is_bounded_and_explicit():
    result,seen=recover({('R04',9):'QUALIFIES'},future_search_days=2)
    assert result['recommended_outcome']=='POSTPONE_AND_REEVALUATE'
    assert len(seen)==8
    assert len(result['search_scope']['future_arrivals_evaluated'])==2
    assert result['search_scope']['continuous_date_search'] is False


def test_unknown_future_cannot_be_no_option():
    result,_=recover({('R04',8):'UNKNOWN'},future_search_days=1)
    assert result['recommended_outcome']=='INSUFFICIENT_DATA'


def test_missing_inputs_does_not_analyze():
    seen=[]
    result=asyncio.run(recover_mission(RecoveryRequest(),fake_analysis({},seen)))
    assert result['recommended_outcome']=='NEEDS_INPUT'
    assert set(result['missing_fields'])=={'original_site_id','original_arrival_utc','study_duration_hours'}
    assert not seen


def test_ranking_earliest_then_longer_then_coverage_then_id():
    def candidate(site,start,duration=180,coverage=1):
        return dict(site_id=site,qualifying_status='QUALIFIES',known_fraction=coverage,earliest_qualifying_window=dict(start_utc=start,duration_minutes=duration))
    a=candidate('R01','2026-11-20T01:00:00Z',200)
    b=candidate('R04','2026-11-20T00:00:00Z',180)
    assert rank_candidates([a,b])[0] is b
    a['earliest_qualifying_window']['start_utc']=b['earliest_qualifying_window']['start_utc']
    assert rank_candidates([a,b])[0] is a
    b['earliest_qualifying_window']['duration_minutes']=200
    assert rank_candidates([b,a])[0] is a
