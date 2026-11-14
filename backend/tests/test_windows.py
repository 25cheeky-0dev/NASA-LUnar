from datetime import datetime, timedelta, timezone
import pytest
from app.metadata import iso
from app.providers.horizons import sky
from app.science.windows import summarize, find_windows

T=datetime(2026,1,1,tzinfo=timezone.utc)


def rows(minutes, step=1, sun=1, earth=1):
    return [dict(timestamp_utc=iso(T+timedelta(minutes=i)),sun=sky(0,sun),earth=sky(180,earth),status='KNOWN') for i in range(0,minutes+1,step)]


@pytest.mark.parametrize('duration,expected',[(179,'FAILS'),(180,'QUALIFIES'),(181,'QUALIFIES')])
def test_duration_threshold(duration,expected):
    result=summarize(rows(duration),T,T+timedelta(minutes=duration),1,180)
    assert result['qualifying_status']==expected
    assert result['shared_windows'][0]['estimate_status']=='MODEL_ESTIMATE'


@pytest.mark.parametrize('sun,earth',[(0,1),(1,0),(-1,1),(1,-1),(0,0)])
def test_strict_target_center_threshold(sun,earth):
    assert not find_windows(rows(180,sun=sun,earth=earth),'BOTH',1)


def test_gap_never_bridges_windows():
    data=rows(240)
    del data[90:151]
    result=summarize(data,T,T+timedelta(minutes=240),1,180)
    assert result['qualifying_status']=='UNKNOWN'
    assert result['unknown_fraction']>0
    assert result['longest_shared_minutes']<180
    assert result['unknown_intervals']


def test_three_separate_hours_do_not_qualify():
    data=rows(240)
    for i in (60,120,180):
        data[i]['sun']=sky(0,-1)
    result=summarize(data,T,T+timedelta(minutes=240),1,180)
    assert result['qualifying_status']=='FAILS'
    assert result['longest_shared_minutes']<60


def test_unknown_target_is_not_zero_or_positive():
    data=rows(180)
    data[90]['earth']=None
    result=summarize(data,T,T+timedelta(minutes=180),1,180)
    assert result['qualifying_status']=='UNKNOWN'
    assert result['unknown_fraction']>0


def test_crossing_is_linear_estimate_not_verified():
    data=rows(10,step=5)
    data[0]['sun']=sky(0,-1)
    data[1]['sun']=sky(0,1)
    window=find_windows(data,'BOTH',5)[0]
    assert window['duration_minutes']==7.5
    assert window['start_utc']==iso(T+timedelta(minutes=2.5))
    assert window['boundary_uncertainty_seconds']==300
    assert window['estimate_status']=='MODEL_ESTIMATE'


def test_sampled_zero_does_not_join_separate_positive_runs():
    data=rows(240)
    data[120]['sun']=sky(0,0)
    windows=find_windows(data,'BOTH',1)
    assert len(windows)==2
    assert max(w['duration_minutes'] for w in windows)==120


def test_one_positive_sample_proves_no_duration():
    result=summarize(rows(0),T,T+timedelta(hours=3),5,180)
    assert result['qualifying_status']=='UNKNOWN'
    assert result['longest_shared_minutes'] is None


def test_unobserved_tail_unknown():
    result=summarize(rows(10,step=5),T,T+timedelta(minutes=12),5,180)
    assert result['unknown_intervals'][-1]['reason']=='UNOBSERVED_TAIL'


def test_sunset_only_within_observed_interval():
    result=summarize(rows(10,step=5),T,T+timedelta(minutes=10),5,180)
    assert result['next_crossings']['sunset']['timestamp_utc'] is None
    assert result['next_crossings']['sunset']['reason']=='not_observed_in_range'
