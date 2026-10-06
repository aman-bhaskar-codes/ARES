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
