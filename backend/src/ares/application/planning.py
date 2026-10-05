from __future__ import annotations

import re

from ares.domain.models import DateWindow, RunMode
from ares.domain.research import ResearchPlan

_YEAR = re.compile(r"\b(19|20)\d{2}\b")


class DeterministicResearchPlanner:
    """Small policy-owned planner.

    The model is intentionally not allowed to choose tool permissions or budgets. This planner
    expands only the discovery query while preserving the user's original wording as variant 1.
    """

    def plan(self, query: str, mode: RunMode, date_window: DateWindow | None = None) -> ResearchPlan:
        cleaned = " ".join(query.split())
        variants = [cleaned]
        lower = cleaned.lower()

        if mode is RunMode.RESEARCH:
            if any(term in lower for term in ("compare", "versus", " vs ", "difference")):
                variants.append(f"{cleaned} official documentation")
                variants.append(f"{cleaned} limitations evaluation")
            elif any(term in lower for term in ("paper", "research", "study", "literature")):
                variants.append(f"{cleaned} paper methodology limitations")
                variants.append(f"{cleaned} review benchmark")
            else:
                variants.append(f"{cleaned} primary source")
                variants.append(f"{cleaned} evidence limitations")

        # Stable dedupe without broadening away from the user's target.
        unique: list[str] = []
        seen: set[str] = set()
        for variant in variants:
            key = variant.casefold()
            if key not in seen:
                unique.append(variant)
                seen.add(key)

        time_range = None
        if date_window is None and not _YEAR.search(cleaned):
            if any(term in lower for term in ("today", "latest", "current", "recent", "this week")):
                time_range = "month"

        facets: list[str] = []
        if mode is RunMode.RESEARCH:
            facets = ["main finding", "supporting evidence", "limitations or disagreement"]
        return ResearchPlan(query_variants=unique, facets=facets, time_range=time_range)
