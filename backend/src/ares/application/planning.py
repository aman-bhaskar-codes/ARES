from __future__ import annotations

import re
from typing import Protocol

from ares.domain.models import DateWindow, RunMode
from ares.domain.research import ResearchPlan

_YEAR = re.compile(r"\b(19|20)\d{2}\b")



class ResearchPlanner(Protocol):
    def plan(self, query: str, mode: RunMode, date_window: DateWindow | None = None) -> ResearchPlan:
        ...

class DeterministicResearchPlanner:
    """Small policy-owned planner.

    The model is intentionally not allowed to choose tool permissions or budgets. This planner
    expands only the discovery query while preserving the user's original wording as variant 1.
    """

    def plan(
        self, query: str, mode: RunMode, date_window: DateWindow | None = None
    ) -> ResearchPlan:
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

        intent = "narrow"
        # Exact DOI/arXiv/repository/quoted-string queries retain deterministic priority.
        if '"' in cleaned or "doi.org" in lower or "arxiv:" in lower or "github.com" in lower:
            intent = "exact"
        elif any(term in lower for term in ("compare", "versus", " vs ", "difference")):
            intent = "comparison"
        elif any(term in lower for term in ("trend", "history", "over time", "development")):
            intent = "temporal"
        elif any(term in lower for term in ("how does", "why is", "impact of", "effect of")):
            intent = "multi-hop"

        subqueries = [cleaned]
        if intent != "exact":
            stopwords = set("what is are a an the and why does do how in of to with explain clearly cited sources source cite please matter me tell use".split())
            terms = [word for word in re.findall(r"[\w-]+", lower) if word not in stopwords]
            compact = " ".join(dict.fromkeys(terms))
            if terms and compact != lower:
                subqueries = [compact, cleaned]
        if mode is RunMode.RESEARCH and intent == "comparison":
            parts = re.split(r'\b(?:versus|vs|compare(?:d to)?|difference between)\b', lower)
            if len(parts) == 2:
                subqueries = [parts[0].strip(), parts[1].strip(), cleaned]
        elif mode is RunMode.RESEARCH and len(unique) > 1 and subqueries == [cleaned]:
            subqueries = [unique[0], unique[1]]

        subqueries = subqueries[:3]

        facets: list[str] = []
        if mode is RunMode.RESEARCH:
            facets = ["main finding", "supporting evidence", "limitations or disagreement"]
            
        return ResearchPlan(
            query_variants=unique, 
            facets=facets, 
            time_range=time_range,
            intent=intent,
            subqueries=subqueries
        )
