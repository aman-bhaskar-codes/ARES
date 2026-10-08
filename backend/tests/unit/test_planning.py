from ares.application.planning import DeterministicResearchPlanner
from datetime import datetime

from ares.domain.models import DateWindow, RunMode


def test_research_planner_preserves_original_and_adds_bounded_variants() -> None:
    plan = DeterministicResearchPlanner().plan("Compare agent memory methods", RunMode.RESEARCH)
    assert plan.query_variants[0] == "Compare agent memory methods"
    assert len(plan.query_variants) <= 3
    assert "limitations or disagreement" in plan.facets


def test_current_query_gets_recent_window_without_overriding_historical_year() -> None:
    planner = DeterministicResearchPlanner()
    assert planner.plan("latest Gemini model", RunMode.QUICK).time_range == "month"
    assert planner.plan("latest Gemini model in 2024", RunMode.QUICK).time_range is None


def test_explicit_date_window_suppresses_relative_recency_filter() -> None:
    window = DateWindow(start=datetime(2024, 1, 1), end=datetime(2024, 12, 31), timezone="UTC")
    plan = DeterministicResearchPlanner().plan("latest Gemini model", RunMode.QUICK, window)
    assert plan.time_range is None


def test_quick_question_uses_compact_search_terms():
    plan = DeterministicResearchPlanner().plan('What is a qubit, and why does decoherence matter in quantum computing? Explain clearly with cited sources.', RunMode.QUICK)
    assert 'qubit decoherence quantum computing' in plan.subqueries


def test_single_topic_questions_are_searchable_in_both_modes():
    for mode in RunMode:
        plan = DeterministicResearchPlanner().plan('what is RSI ?', mode)
        assert plan.subqueries[0] == 'rsi'
        assert plan.query_variants[0] == 'what is RSI ?'
