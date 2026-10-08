from __future__ import annotations

import json
import re
from typing import Any


from ares.domain.models import DateWindow, RunMode
from ares.domain.research import ResearchPlan
from ares.application.planning import DeterministicResearchPlanner

_PLAN_SYSTEM_INSTRUCTION = """You are the research planner for ARES.
Analyze the USER_QUERY and context to produce a structured ResearchPlan.

OUTPUT SCHEMA:
Return a JSON object matching the ResearchPlan schema.
intent options: "exact", "narrow", "comparison", "multi-hop", "temporal", "analysis"
time_range options: "day", "week", "month", "year", or null
language: "all" or an ISO language code such as "en"; never a language name.
subqueries: up to 3 focused search queries for finding evidence.
query_variants: up to 8 variations.
facets: up to 12 strings describing facets to cover.

RULES:
- Exact DOI/arXiv/repository/quoted-string queries retain deterministic priority (intent: exact, 1 subquery).
- Do not invent tools or document IDs.
- For comparisons, produce subqueries for each entity.
"""

class GeminiResearchPlanner:
    def __init__(self, api_key: str, model: str = "gemini-3.8-flash", client: Any | None = None):
        self._fallback = DeterministicResearchPlanner()
        self._model = model
        if client is None:
            try:
                from google import genai
                from google.genai import types
            except ImportError:
                self._client = None
                return
            if not api_key:
                self._client = None
                return
            self._client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=10000),
            )
        else:
            self._client = client
            
    def plan(
        self, query: str, mode: RunMode, date_window: DateWindow | None = None
    ) -> ResearchPlan:
        if self._client is None:
            return self._fallback.plan(query, mode, date_window)
            
        try:
            from google.genai import types
            response = self._client.models.generate_content(
                model=self._model,
                contents=json.dumps({"USER_QUERY": query, "MODE": mode.value, "HAS_DATE_WINDOW": date_window is not None}),
                config=types.GenerateContentConfig(
                    system_instruction=_PLAN_SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=ResearchPlan,
                    temperature=0.1,
                )
            )
            data = json.loads(response.text)
            language = data.get("language", "all")
            # Model output is untrusted: SearXNG rejects names such as "English".
            if not isinstance(language, str) or not re.fullmatch(r"all|[a-z]{2}(?:-[A-Za-z]{2})?", language):
                data["language"] = "all"
            return ResearchPlan.model_validate(data)
        except Exception:
            return self._fallback.plan(query, mode, date_window)
