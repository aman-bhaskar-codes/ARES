from unittest.mock import MagicMock
from ares.application.gemini_planner import GeminiResearchPlanner
from ares.domain.research import ResearchPlan
from ares.domain.models import RunMode

def test_gemini_planner_injection_cannot_invent_tools_or_documents():
    planner = GeminiResearchPlanner("test-key")
    # We mock the internal _client
    mock_client = MagicMock()
    planner._client = mock_client
    
    mock_response = MagicMock()
    import json
    mock_response.text = json.dumps({
        "query_variants": ["test variant"],
        "facets": ["test facet"],
        "language": "en",
        "intent": "narrow",
        "subqueries": ["sub 1", "sub 2"]
    })
    mock_client.models.generate_content.return_value = mock_response

    plan = planner.plan("test query", RunMode.QUICK)
    assert plan.intent == "narrow"
    assert len(plan.subqueries) == 2
    assert plan.subqueries == ["sub 1", "sub 2"]


def test_planner_does_not_pass_language_names_to_search():
    import json
    from types import SimpleNamespace

    response = SimpleNamespace(text=json.dumps({
        'language': 'English', 'intent': 'comparison',
        'subqueries': ['RAG vs fine-tuning'], 'query_variants': ['RAG vs fine-tuning'], 'facets': [],
    }))
    client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: response))
    plan = GeminiResearchPlanner('', client=client).plan('Compare RAG and fine-tuning', RunMode.QUICK)
    assert plan.language == 'all'
    assert plan.subqueries == ['RAG vs fine-tuning']
