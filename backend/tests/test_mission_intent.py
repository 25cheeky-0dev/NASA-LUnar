import asyncio
import pytest
from pydantic import ValidationError
from app.mission_intent import validated_intent, interpret_mission
from app.providers.interpret import InterpretRequest


def test_schema_rejects_science_invention():
    with pytest.raises(ValidationError):
        validated_intent('{"landing_probability":0.99}', 'find a site')
    with pytest.raises(ValidationError):
        validated_intent('{"start_utc":"2026-02-30T00:00:00Z"}', '2026-02-30')
    with pytest.raises(ValidationError):
        validated_intent('{"start_utc":"2026-11-15T00:00:00+05:30"}', 'local date')


def test_critical_fields_require_literal_user_evidence():
    raw='{"start_utc":"2026-11-15T00:00:00Z","duration_hours":168,"minimum_shared_minutes":60}'
    assert validated_intent(raw,'next week')['needs_clarification']
    result=validated_intent(raw,'2026-11-15 00:00 UTC for 168 hours with 60 minutes shared')
    assert result['needs_clarification'] is False


def test_no_key_preserves_manual_workflow(monkeypatch):
    for provider in ('GROQ','NVIDIA'):
        monkeypatch.delenv(provider+'_API_KEY',raising=False)
    result=asyncio.run(interpret_mission(InterpretRequest(text='find safe landings')))
    assert result['status']=='LLM_UNAVAILABLE'
    assert result['inputs'] is None
