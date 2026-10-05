from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ares.domain.decisions import (
    ClaimDecision,
    ClaimVerdict,
    CoverageDecision,
    ResearchTask,
    RouteDecision,
)
from ares.domain.research import EvidencePacket


class JevProviderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class JevConfig:
    api_key: str
    model: str = "jev-latest"
    base_url: str = "https://api.typesafe.ai"
    timeout_seconds: float = 12.0


class JevDecisionProvider:
    """Typed TypeSafe/Jev adapter for routing and evaluation.

    Jev is never allowed to choose tool permissions, URLs, credentials, or budgets. It only
    answers narrow typed questions. Network/auth/schema failures are explicit so the caller can
    fail closed to deterministic policy when configured to do so.
    """

    def __init__(self, config: JevConfig, *, client: httpx.Client | None = None):
        if not config.api_key.strip():
            raise ValueError("Jev API key is required")
        self.config = config
        self._client = client or httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=config.timeout_seconds,
            headers={"Authorization": f"Bearer {config.api_key}"},
        )

    def _ask(self, state: Any, questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        try:
            response = self._client.post(
                "/v1/systemone",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                json={"state": state, "model": self.config.model, "questions": questions},
            )
        except httpx.HTTPError as exc:
            raise JevProviderError(f"Jev request failed: {type(exc).__name__}") from exc
        if response.status_code == 429:
            raise JevProviderError("Jev allowance exhausted or rate limited")
        if response.status_code in {401, 403}:
            raise JevProviderError("Jev credentials were rejected")
        if response.status_code >= 400:
            raise JevProviderError(f"Jev returned HTTP {response.status_code}")
        try:
            payload = response.json()
            answers = payload["answers"]
        except (ValueError, KeyError, TypeError) as exc:
            raise JevProviderError("Jev returned an invalid response schema") from exc
        if not isinstance(answers, dict):
            raise JevProviderError("Jev answers were not an object")
        return answers

    def route(self, query: str) -> RouteDecision:
        answers = self._ask(
            {"query": query},
            {
                "task": {
                    "type": "choice",
                    "instructions": "Classify the primary research task requested by the user.",
                    "criteria": {
                        "explanation": "General factual or explanatory research.",
                        "comparison": "Compares two or more alternatives, methods, or claims.",
                        "current_events": "Requires current, latest, recent, or time-sensitive information.",
                        "literature": "Asks about research papers, scientific literature, methods, or evidence.",
                        "software": "Asks about software packages, repositories, releases, APIs, or code.",
                        "document": "Asks about user-supplied documents or a bounded document collection.",
                    },
                },
                "academic": {
                    "type": "noul",
                    "instructions": "Would scholarly metadata or academic papers materially improve this research?",
                },
                "software": {
                    "type": "noul",
                    "instructions": "Would software repository or release metadata materially improve this research?",
                },
                "current_web": {
                    "type": "noul",
                    "instructions": "Does this task benefit from current public web sources?",
                },
            },
        )
        task_answer = answers.get("task", {})
        raw_task = str(task_answer.get("choice", "explanation"))
        try:
            task = ResearchTask(raw_task)
        except ValueError:
            task = ResearchTask.EXPLANATION
        probabilities = task_answer.get("probabilities", {})
        confidence = float(task_answer.get("confidence", probabilities.get(raw_task, 0.5)))
        return RouteDecision(
            task=task,
            needs_academic=float(answers.get("academic", {}).get("noul", 0.0)) >= 0.55,
            needs_software=float(answers.get("software", {}).get("noul", 0.0)) >= 0.55,
            needs_current_web=float(answers.get("current_web", {}).get("noul", 1.0)) >= 0.45,
            confidence=max(0.0, min(1.0, confidence)),
            provider=f"jev:{self.config.model}",
        )

    def evaluate_coverage(
        self, query: str, facets: list[str], evidence: list[EvidencePacket]
    ) -> CoverageDecision:
        state = {
            "query": query,
            "required_facets": facets,
            "evidence": [
                {"title": item.title, "locator": item.locator, "text": item.text[:1800]}
                for item in evidence[:16]
            ],
        }
        questions: dict[str, dict[str, Any]] = {
            "overall": {
                "type": "noul",
                "instructions": "Is the supplied evidence sufficient to answer the user query without a material unsupported gap?",
                "criteria": {
                    "true": "The important requested dimensions can be answered directly from the evidence.",
                    "false": "At least one important requested dimension is missing or weakly supported.",
                },
            }
        }
        for index, facet in enumerate(facets[:8]):
            questions[f"facet_{index}"] = {
                "type": "noul",
                "instructions": f"Is there adequate direct evidence for this required facet: {facet}?",
            }
        answers = self._ask(state, questions)
        overall = float(answers.get("overall", {}).get("noul", 0.0))
        missing = [
            facet
            for index, facet in enumerate(facets[:8])
            if float(answers.get(f"facet_{index}", {}).get("noul", 0.0)) < 0.55
        ]
        return CoverageDecision(
            sufficient=overall >= 0.68 and not missing,
            confidence=abs(overall - 0.5) * 2.0,
            missing_facets=missing,
            provider=f"jev:{self.config.model}",
        )

    def evaluate_claim(self, claim: str, evidence: list[EvidencePacket]) -> ClaimDecision:
        answers = self._ask(
            {
                "claim": claim,
                "evidence": [
                    {"title": item.title, "locator": item.locator, "text": item.text[:2200]}
                    for item in evidence[:8]
                ],
            },
            {
                "support": {
                    "type": "choice",
                    "instructions": "Classify how the supplied evidence bears on the claim. Judge only the supplied evidence, not outside knowledge.",
                    "criteria": {
                        "supported": "The evidence directly supports the material claim and its scope.",
                        "partially_supported": "Some material part or scope of the claim is not directly supported.",
                        "conflicting": "Relevant supplied evidence supports incompatible conclusions for this claim.",
                        "insufficient_evidence": "The supplied evidence does not adequately support the claim.",
                    },
                }
            },
        )
        answer = answers.get("support", {})
        raw = str(answer.get("choice", "insufficient_evidence"))
        mapping = {
            "supported": ClaimVerdict.SUPPORTED,
            "partially_supported": ClaimVerdict.PARTIAL,
            "conflicting": ClaimVerdict.CONFLICTING,
            "insufficient_evidence": ClaimVerdict.INSUFFICIENT,
        }
        return ClaimDecision(
            verdict=mapping.get(raw, ClaimVerdict.INSUFFICIENT),
            confidence=max(0.0, min(1.0, float(answer.get("confidence", 0.5)))),
            provider=f"jev:{self.config.model}",
            checker_method="jev_semantic_assessment",
            checker_version=self.config.model,
            assessment_state="semantic_assessed",
            rationale="Typed semantic assessment over the supplied linked evidence.",
        )

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()
