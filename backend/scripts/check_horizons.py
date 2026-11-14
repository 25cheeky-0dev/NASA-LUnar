"""Real-source development example; never selects a mission date for the user."""
import asyncio
import json
from pathlib import Path
from app.main import recovery
from app.schemas import RecoveryRequest


async def main():
    request=RecoveryRequest(original_site_id='R01',original_arrival_utc='2026-11-20T00:00:00Z',study_duration_hours=24)
    result=await recovery(request)
    output=Path('data/evidence')
    output.mkdir(parents=True,exist_ok=True)
    (output/'development_recovery.json').write_text(json.dumps(result,indent=2))
    summary=dict(example_only=True,request=request.model_dump(mode='json'),recommended_outcome=result['recommended_outcome'],
        source_type=result['source_type'],scenarios=[{k:s[k] for k in ('site_id','arrival_utc','end_utc','qualifying_status','longest_shared_minutes','source_type','reason_codes','provenance')} for s in result['original_scenarios']+result['delayed_scenarios']])
    print(json.dumps(summary,indent=2))
    (output/'smoke_summary.json').write_text(json.dumps(summary,indent=2))


if __name__=='__main__':
    asyncio.run(main())
