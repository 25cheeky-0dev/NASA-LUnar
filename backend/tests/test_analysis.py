import asyncio
from datetime import datetime,timedelta,timezone
from app.metadata import iso,metadata
from app.providers.horizons import sky
from app.schemas import RecoveryRequest
from app.science.analysis import analyze_scenario


def test_source_revision_is_part_of_scenario_identity():
    start=datetime(2026,11,20,tzinfo=timezone.utc)
    class Provider:
        digest='synthetic-test-revision-a'
        async def ephemeris(self,request):
            rows=[dict(timestamp_utc=iso(start+timedelta(minutes=i)),sun=sky(0,1),earth=sky(180,1),status='KNOWN',gap_reason=None) for i in range(0,181,5)]
            return dict(records=rows,**metadata('SYNTHETIC_TEST_ONLY',provenance={'raw_sha256':[self.digest]}))
    provider=Provider()
    request=RecoveryRequest()
    a=asyncio.run(analyze_scenario('R01',start,start+timedelta(hours=3),request,provider))
    provider.digest='synthetic-test-revision-b'
    b=asyncio.run(analyze_scenario('R01',start,start+timedelta(hours=3),request,provider))
    assert a['scenario_id']!=b['scenario_id']
    assert a['qualifying_status']=='QUALIFIES'
