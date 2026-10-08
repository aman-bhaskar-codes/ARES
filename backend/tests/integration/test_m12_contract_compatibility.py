from uuid import uuid4
from datetime import datetime, UTC
import pytest
from pydantic import ValidationError

from ares.domain.models import EventEnvelope, RunSnapshot

def test_legacy_schema_supported():
    payload = {
        "schema_version": 1,
        "run_id": str(uuid4()),
        "seq": 1,
        "event_type": "status",
        "at": datetime.now(UTC).isoformat(),
        "payload": {}
    }
    envelope = EventEnvelope.model_validate(payload)
    assert envelope.schema_version == 1

def test_unknown_additive_events_ignored():
    payload = {
        "schema_version": 2,
        "run_id": str(uuid4()),
        "seq": 2,
        "event_type": "new_unseen_event",
        "at": datetime.now(UTC).isoformat(),
        "payload": {"future_field": "test"},
        "future_field_on_envelope": True
    }
    envelope = EventEnvelope.model_validate(payload)
    assert envelope.event_type == "new_unseen_event"
    assert envelope.payload == {"future_field": "test"}

def test_missing_required_fields_fails():
    payload = {
        "schema_version": 2,
        "seq": 3,
        "event_type": "status",
        "at": datetime.now(UTC).isoformat()
    }
    with pytest.raises(ValidationError) as exc:
        EventEnvelope.model_validate(payload)
    assert "run_id" in str(exc.value)

def test_legacy_run_snapshot_schema_supported():
    payload = {
        "id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "query": "test query",
        "mode": "quick",
        "source_scope": [],
        "document_ids": [],
        "status": "completed",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    snapshot = RunSnapshot.model_validate(payload)
    assert snapshot.usage_ledger == {}
    assert snapshot.last_seq == 0
