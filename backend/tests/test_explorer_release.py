import asyncio
import hashlib
import json
import sqlite3
import pytest
import httpx
from fastapi.testclient import TestClient
from app.main import app
from app import persistence
from app.providers import gemini
from app.mission_intent import interpret_mission
from app.providers.interpret import InterpretRequest


def test_evidence_survives_new_connections_and_detects_tampering(tmp_path, monkeypatch):
    monkeypatch.delenv('WISPR_EVIDENCE_BUCKET', raising=False)
    path = tmp_path/'evidence.sqlite'
    monkeypatch.setenv('WISPR_DB_PATH', str(path))
    value={'measurements':[None,0,1.2], 'source_sha256':'a'*64}
    key=persistence.save(value)
    assert persistence.read(key)==value
    assert persistence.save(value)==key
    with sqlite3.connect(path) as db:
        db.execute('UPDATE evidence SET payload=? WHERE id=?',(b'{}',key))
    with pytest.raises(ValueError,match='checksum'):
        persistence.read(key)
    with pytest.raises(KeyError):
        persistence.read('../escape')


def test_report_demo_is_reproducible_and_persistent(tmp_path, monkeypatch):
    monkeypatch.setenv('WISPR_DB_PATH',str(tmp_path/'evidence.sqlite'))
    monkeypatch.delenv('WISPR_EVIDENCE_BUCKET',raising=False)
    with TestClient(app) as client:
        response=client.post('/api/v1/explorer/demo')
        assert response.status_code==200,response.text
        data=response.json()
        assert data['result']['outcome']=='KEEP'
        assert data['result']['delivery_mode']=='PRESERVED_REAL_DATA_OFFLINE'
        exported=client.get(data['report_url'])
        assert exported.status_code==200
        assert hashlib.sha256(persistence.canonical(exported.json())).hexdigest()==data['report_id']
        assert exported.json()['delay_hours']==168
        assert client.get('/api/v1/explorer/reports/'+'0'*64).status_code==404


def test_surface_missing_source_is_not_fabricated(tmp_path, monkeypatch):
    monkeypatch.setenv('WISPR_GLOBAL_ROOT',str(tmp_path))
    with TestClient(app) as client:
        assert client.get('/api/v1/explorer/surface').status_code==503
        assert client.get('/api/v1/explorer/surface?resolution=5000').status_code==422


def test_gemini_uses_header_auth_and_validated_inputs(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','test-key-not-real')
    monkeypatch.setenv('GEMINI_MODEL','test-model')
    captured=[]
    def respond(request):
        captured.append(request)
        value={'start_utc':'2026-11-15T00:00:00Z','duration_hours':168,'minimum_shared_minutes':60}
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(value)}]}}]})
    original=httpx.AsyncClient
    monkeypatch.setattr(gemini.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    result=asyncio.run(interpret_mission(InterpretRequest(text='2026-11-15 00:00 UTC, 168 hours, 60 minutes',provider_preference='gemini')))
    assert result['status']=='REVIEW_REQUIRED'
    assert not result['needs_clarification']
    assert captured[0].headers['x-goog-api-key']=='test-key-not-real'
    assert 'test-key' not in str(captured[0].url)
    # Unsupported dates/units cannot be invented even by a successful provider.
    result=asyncio.run(interpret_mission(InterpretRequest(text='pick the safest spot tomorrow',provider_preference='gemini')))
    assert result['needs_clarification']
    assert result['inputs']['start_utc'] is None


def test_gemini_failure_returns_manual_workflow(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','test-key-not-real')
    monkeypatch.setenv('GEMINI_MODEL','test-model')
    async def fail(*args):
        raise ValueError('invalid response')
    monkeypatch.setattr(gemini,'extract',fail)
    result=asyncio.run(interpret_mission(InterpretRequest(text='168 hours',provider_preference='gemini')))
    assert result['inputs'] is None
    assert result['status']=='LLM_UNAVAILABLE'
