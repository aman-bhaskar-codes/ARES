from __future__ import annotations

from uuid import uuid4

from ares.adapters.db import build_session_factory
from ares.api.app import create_app
from ares.application.identity import Principal, WorkspaceRole, principal_scope
from ares.application.repository import Repository
from ares.domain.memory import EpisodeCreate, FactCreate, PreferenceUpdate
from fastapi.testclient import TestClient


def test_memory_repository_episodes(tmp_path):
    db_path = tmp_path / "memory_test.sqlite3"
    engine, session_factory = build_session_factory(f"sqlite:///{db_path}")
    from ares.adapters.db import Base
    Base.metadata.create_all(engine)

    repo = Repository(session_factory)
    workspace_id = uuid4()
    user_id = uuid4()

    # 1. Create episode
    ep1 = repo.create_memory_episode(
        workspace_id,
        user_id,
        EpisodeCreate(
            title="Quantum Computing Advancements",
            summary="Discussion of topological qubits and error thresholds exceeding 99.9%.",
            key_findings=["Topological qubits show 10x longer coherence.", "Surface codes require 1000 physical qubits per logical qubit."],
            importance=0.8,
        ),
    )
    assert ep1.title == "Quantum Computing Advancements"
    assert ep1.importance == 0.8
    assert len(ep1.key_findings) == 2

    # 2. List episodes
    episodes = repo.list_memory_episodes(workspace_id)
    assert len(episodes) == 1
    assert episodes[0].id == ep1.id

    # 3. Search episodes
    results = repo.search_memory_episodes(workspace_id, "topological qubits", limit=5)
    assert len(results) == 1
    scored_ep, score = results[0]
    assert scored_ep.id == ep1.id
    assert score > 0.0

    # 4. Delete episode
    assert repo.delete_memory_episode(ep1.id, workspace_id) is True
    assert repo.get_memory_episode(ep1.id, workspace_id) is None


def test_memory_repository_facts_and_consolidation(tmp_path):
    db_path = tmp_path / "memory_facts_test.sqlite3"
    engine, session_factory = build_session_factory(f"sqlite:///{db_path}")
    from ares.adapters.db import Base
    Base.metadata.create_all(engine)

    repo = Repository(session_factory)
    workspace_id = uuid4()
    user_id = uuid4()

    # 1. Create an initial fact
    fact1 = repo.create_memory_fact(
        workspace_id,
        user_id,
        FactCreate(
            subject="Python 3.12",
            predicate="has_gil",
            fact="Python 3.12 retains the Global Interpreter Lock by default.",
            confidence=1.0,
        ),
    )
    assert fact1.status == "active"

    # 2. Search facts
    results = repo.search_memory_facts(workspace_id, "Interpreter Lock")
    assert len(results) == 1
    assert results[0][0].id == fact1.id

    # 3. Add newer conflicting fact (Python 3.13 free-threaded)
    fact2 = repo.create_memory_fact(
        workspace_id,
        user_id,
        FactCreate(
            subject="Python 3.12",
            predicate="has_gil",
            fact="Python 3.12 with experimental free-threading build disables GIL.",
            confidence=0.9,
        ),
    )

    # 4. Consolidate facts (dedupes / supersedes older conflicting predicate)
    stats = repo.consolidate_memory_facts(workspace_id)
    assert stats["superseded_facts"] == 1
    assert stats["active_facts"] == 1

    # Check that fact1 was superseded by fact2
    refreshed_fact1 = repo.get_memory_fact(fact1.id, workspace_id)
    assert refreshed_fact1 is not None
    assert refreshed_fact1.status == "superseded"
    assert refreshed_fact1.superseded_by_id == fact2.id


def test_memory_preferences(tmp_path):
    db_path = tmp_path / "memory_pref_test.sqlite3"
    engine, session_factory = build_session_factory(f"sqlite:///{db_path}")
    from ares.adapters.db import Base
    Base.metadata.create_all(engine)

    repo = Repository(session_factory)
    workspace_id = uuid4()
    user_id = uuid4()

    # 1. Default preferences
    pref = repo.get_memory_preferences(workspace_id, user_id)
    assert pref.depth == "standard"
    assert pref.tone == "academic"

    # 2. Update preferences
    updated = repo.update_memory_preferences(
        workspace_id,
        user_id,
        PreferenceUpdate(
            depth="deep",
            preferred_domains=["arxiv.org", "nature.com"],
            tone="technical",
            custom_instructions="Focus on empirical methodology.",
        ),
    )
    assert updated.depth == "deep"
    assert updated.tone == "technical"
    assert "arxiv.org" in updated.preferred_domains
    assert updated.custom_instructions == "Focus on empirical methodology."


def test_memory_api_endpoints(monkeypatch, tmp_path):
    db_path = tmp_path / "memory_api.sqlite3"
    engine, session_factory = build_session_factory(f"sqlite:///{db_path}")
    from ares.adapters.db import Base
    Base.metadata.create_all(engine)

    app = create_app()
    app.state.repository = Repository(session_factory)
    app.state.db_engine = engine

    workspace_id = uuid4()
    user_id = uuid4()
    test_principal = Principal(
        user_id=user_id,
        workspace_id=workspace_id,
        role=WorkspaceRole.OWNER,
        subject="test-user",
    )

    client = TestClient(app)

    with principal_scope(test_principal):
        # 1. Create episode via API
        resp = client.post(
            "/api/v1/memory/episodes",
            json={
                "title": "Autonomous Agents Survey",
                "summary": "Survey covering tool-use, memory reflection, and multi-agent coordination.",
                "key_findings": ["Reflexion loops boost task completion."],
                "importance": 0.9,
            },
        )
        assert resp.status_code == 201, resp.text
        episode_id = resp.json()["id"]

        # 2. Search episode via API
        resp = client.get("/api/v1/memory/episodes/search?q=Reflexion")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["episode"]["id"] == episode_id

        # 3. Create fact via API
        resp = client.post(
            "/api/v1/memory/facts",
            json={
                "subject": "ARES System",
                "predicate": "architecture",
                "fact": "ARES features a 4-tier memory architecture.",
                "confidence": 1.0,
            },
        )
        assert resp.status_code == 201
        fact_id = resp.json()["id"]

        # 4. Search facts via API
        resp = client.get("/api/v1/memory/facts/search?q=memory architecture")
        assert resp.status_code == 200
        facts = resp.json()
        assert len(facts) >= 1
        assert facts[0]["fact"]["id"] == fact_id

        # 5. Get and update preferences via API
        resp = client.get("/api/v1/memory/preferences")
        assert resp.status_code == 200
        assert resp.json()["depth"] == "standard"

        resp = client.put(
            "/api/v1/memory/preferences",
            json={"depth": "deep", "tone": "brief"},
        )
        assert resp.status_code == 200
        assert resp.json()["depth"] == "deep"
        assert resp.json()["tone"] == "brief"
