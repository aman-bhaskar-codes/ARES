from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from ares.adapters.jev import JevProviderError
from ares.domain.decisions import (
    ClaimDecision,
    ClaimVerdict,
    CoverageDecision,
    FacetAssessment,
    FacetStatus,
    ResearchTask,
    RouteDecision,
)
from ares.domain.research import EvidencePacket
from ares.ports.decisions import DecisionProvider


_TOKEN = re.compile(r"[\w'-]+", re.UNICODE)
_QUANTITY = re.compile(
    r"(?<![\w.])(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*(?P<unit>%|percentage\s+points?|percent(?:age)?(?:\s+points?)?|ms|seconds?|minutes?|hours?|days?|"
    r"kb|mb|gb|tb|km|miles?|meters?|metres?|cm|mm|kg|grams?|usd|eur|gbp|inr)?(?!\w)",
    re.IGNORECASE,
)
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "is",
    "it", "of", "on", "or", "that", "the", "this", "to", "was", "were", "will", "with",
}
_NEGATION = {"no", "not", "never", "none", "without", "cannot", "can't", "didn't", "doesn't", "isn't", "wasn't"}
_POLARITY_PAIRS = (
    ({"increase", "increased", "higher"}, {"decrease", "decreased", "lower"}),
    ({"improve", "improved", "better"}, {"worse", "worsened"}),
    ({"faster"}, {"slower"}),
    ({"support", "supported", "enable", "enabled", "allow", "allowed"}, {"reject", "rejected", "block", "blocked", "prevent", "prevented", "disable", "disabled"}),
)


_ALIASES = {
    "keys": "key", "uses": "use", "parser": "parse", "parsing": "parse", "parsed": "parse",
    "subprocess": "process", "subprocesses": "process", "runs": "run", "running": "run",
}


def _normalize_term(term: str) -> str:
    value = term.casefold()
    if value in _ALIASES:
        return _ALIASES[value]
    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"
    if value.endswith("s") and not value.endswith("ss") and len(value) > 4:
        return value[:-1]
    return value


def _content_tokens(text: str) -> list[str]:
    output = []
    for match in _TOKEN.finditer(text):
        term = _normalize_term(match.group(0))
        if (len(term) > 2 or any(character.isdigit() for character in term)) and term not in _STOP:
            output.append(term)
    return output


def _quantities(text: str) -> set[tuple[str, str | None]]:
    aliases = {
        "%": "percent", "percentage": "percent", "percent": "percent",
        "percentage point": "percentage_point", "percentage points": "percentage_point",
        "percent point": "percentage_point", "percent points": "percentage_point",
        "second": "s", "seconds": "s", "minute": "min", "minutes": "min",
        "hour": "h", "hours": "h", "meter": "m", "meters": "m", "metre": "m", "metres": "m",
        "mile": "mi", "miles": "mi", "gram": "g", "grams": "g",
    }
    result: set[tuple[str, str | None]] = set()
    for match in _QUANTITY.finditer(text):
        raw = match.group("number").replace(",", "")
        try:
            number = format(Decimal(raw).normalize(), "f")
        except InvalidOperation:
            number = raw.casefold()
        unit = match.group("unit")
        normalized = aliases.get(unit.casefold().strip(), unit.casefold().strip()) if unit else None
        result.add((number, normalized))
    return result


def _polarity_conflict(claim_tokens: set[str], evidence_tokens: set[str]) -> bool:
    claim_negated = bool(claim_tokens & _NEGATION)
    evidence_negated = bool(evidence_tokens & _NEGATION)
    if claim_negated != evidence_negated and len((claim_tokens - _NEGATION) & (evidence_tokens - _NEGATION)) >= 2:
        return True
    for positive, negative in _POLARITY_PAIRS:
        if claim_tokens & positive and evidence_tokens & negative:
            return True
        if claim_tokens & negative and evidence_tokens & positive:
            return True
    return False


class DeterministicDecisionProvider:
    """Fail-closed decisions that keep ARES operational without a metered model."""

    def route(self, query: str) -> RouteDecision:
        lower = query.casefold()
        if any(term in lower for term in ("uploaded document", "uploaded file", "attached file", "this pdf", "this document", "my document")):
            task = ResearchTask.DOCUMENT
        elif any(term in lower for term in ("paper", "papers", "literature", "study", "studies", "research article", "research articles", "doi", "arxiv")):
            task = ResearchTask.LITERATURE
        elif any(term in lower for term in ("compare", " vs ", "versus", "difference between")):
            task = ResearchTask.COMPARISON
        elif any(term in lower for term in ("release", "github", "package", "library", "api", "framework", "version")):
            task = ResearchTask.SOFTWARE
        elif any(term in lower for term in ("latest", "today", "current", "recent", "this week", "news")):
            task = ResearchTask.CURRENT
        else:
            task = ResearchTask.EXPLANATION
        return RouteDecision(
            task=task,
            needs_academic=task is ResearchTask.LITERATURE,
            needs_software=task is ResearchTask.SOFTWARE,
            needs_current_web=task is not ResearchTask.DOCUMENT,
            confidence=0.75,
            provider="deterministic",
        )

    def evaluate_coverage(
        self, query: str, facets: list[str], evidence: list[EvidencePacket]
    ) -> CoverageDecision:
        if not evidence:
            return CoverageDecision(
                sufficient=False, confidence=1.0, missing_facets=facets,
                facets=[FacetAssessment(facet=facet, status=FacetStatus.MISSING, rationale="no evidence was retrieved") for facet in facets],
            )

        # Count independent source origins, not passages or domains. Mirrors, abstracts and
        # metadata rows sharing an origin group must not inflate apparent corroboration.
        origins = {packet.origin_group_id or packet.source_id for packet in evidence}
        query_terms = set(_content_tokens(query))
        limitation_terms = {
            "limit", "limitation", "caveat", "bias", "uncertain", "uncertainty", "conflict",
            "disagree", "disagreement", "however", "but", "risk", "weakness", "failure",
        }
        facet_rows: list[FacetAssessment] = []
        for facet in facets:
            lower = facet.casefold()
            candidates: list[EvidencePacket] = []
            if "limitation" in lower or "disagreement" in lower or "conflict" in lower:
                candidates = [packet for packet in evidence if set(_content_tokens(packet.text)) & limitation_terms]
            else:
                for packet in evidence:
                    packet_terms = set(_content_tokens(packet.text))
                    if not query_terms or len(packet_terms & query_terms) >= min(2, max(1, len(query_terms) // 4)):
                        candidates.append(packet)
            # Preserve independent origins while keeping deterministic source order.
            selected: list[EvidencePacket] = []
            seen_origins = set()
            for packet in candidates:
                origin = packet.origin_group_id or packet.source_id
                if origin in seen_origins:
                    continue
                seen_origins.add(origin)
                selected.append(packet)
                if len(selected) >= 3:
                    break
            if selected:
                facet_rows.append(FacetAssessment(
                    facet=facet, status=FacetStatus.SUPPORTED,
                    supporting_evidence_ids=[packet.evidence_id for packet in selected],
                    rationale=f"mapped to {len(selected)} independent evidence origin(s)",
                ))
            else:
                facet_rows.append(FacetAssessment(
                    facet=facet, status=FacetStatus.MISSING, rationale="no evidence mapped to this required facet",
                ))

        missing = [row.facet for row in facet_rows if row.status is FacetStatus.MISSING]
        # Quick mode has no explicit facets; preserve the existing conservative minimum while
        # replacing domain-count inflation with independent-origin counting.
        if not facets:
            enough = len(evidence) >= 3 and len(origins) >= min(2, len(evidence))
        else:
            enough = not missing and len(origins) >= min(2, len(evidence))
        return CoverageDecision(
            sufficient=enough, confidence=0.72 if facets else 0.65,
            missing_facets=missing if facets else ([] if enough else []), facets=facet_rows, provider="deterministic",
        )

    def evaluate_claim(self, claim: str, evidence: list[EvidencePacket]) -> ClaimDecision:
        if not evidence:
            return ClaimDecision(
                verdict=ClaimVerdict.INSUFFICIENT, confidence=1.0, provider="deterministic",
                assessment_state="deterministic_exact", rationale="no evidence was supplied",
            )
        claim_terms = _content_tokens(claim)
        if not claim_terms:
            return ClaimDecision(
                verdict=ClaimVerdict.INSUFFICIENT, confidence=0.9, provider="deterministic",
                rationale="claim had no material lexical content after normalization",
            )
        claim_values = _quantities(claim)
        compatible = []
        incompatible_quantity = False
        claim_set = set(claim_terms)
        for packet in evidence:
            evidence_set = set(_content_tokens(packet.text))
            overlap = sum(1 for term in claim_terms if term in evidence_set) / max(1, len(claim_terms))
            quantity_ok = not claim_values or claim_values.issubset(_quantities(packet.text))
            incompatible_quantity = incompatible_quantity or (not quantity_ok and overlap >= 0.45)
            compatible.append((overlap, _polarity_conflict(claim_set, evidence_set), quantity_ok))
        usable = [(score, conflict) for score, conflict, ok in compatible if ok]
        if claim_values and not usable:
            rendered = ", ".join(f"{n}{' ' + u if u else ''}" for n, u in sorted(claim_values))
            return ClaimDecision(
                verdict=ClaimVerdict.INSUFFICIENT, confidence=0.98, provider="deterministic",
                checker_method="deterministic_numeric_unit_guard", assessment_state="deterministic_exact",
                rationale=f"evidence does not contain the claim quantity or compatible unit: {rendered}",
            )
        strongest = max((score for score, _ in usable), default=0.0)
        if incompatible_quantity and usable:
            return ClaimDecision(
                verdict=ClaimVerdict.CONFLICTING, confidence=0.9, provider="deterministic",
                checker_method="deterministic_numeric_unit_guard", assessment_state="deterministic_exact",
                rationale="evidence contains incompatible numeric or unit values",
            )
        if any(conflict for _, conflict in usable) and any(score >= 0.45 and not conflict for score, conflict in usable):
            return ClaimDecision(
                verdict=ClaimVerdict.CONFLICTING, confidence=0.9,
                checker_method="deterministic_polarity_guard", assessment_state="deterministic_exact",
                rationale="supporting and polarity-conflicting evidence are both present",
            )
        if usable and all(conflict for _, conflict in usable) and strongest >= 0.35:
            return ClaimDecision(
                verdict=ClaimVerdict.INSUFFICIENT, confidence=0.9,
                checker_method="deterministic_polarity_guard", assessment_state="deterministic_exact",
                rationale="available evidence conflicts with claim polarity",
            )
        if strongest >= 0.65:
            return ClaimDecision(verdict=ClaimVerdict.SUPPORTED, confidence=min(0.9, 0.55 + strongest / 2), rationale="material overlap and explicit quantities are compatible")
        if strongest >= 0.42:
            return ClaimDecision(verdict=ClaimVerdict.PARTIAL, confidence=min(0.8, 0.45 + strongest / 3), rationale="evidence overlap is partial")
        return ClaimDecision(verdict=ClaimVerdict.INSUFFICIENT, confidence=max(0.55, 1.0 - strongest), rationale="evidence does not meet the deterministic support threshold")



class ResilientDecisionProvider:
    """Use Jev when configured, but never let a decision-provider outage break research."""

    def __init__(self, primary: DecisionProvider | None, fallback: DecisionProvider | None = None):
        self.primary = primary
        self.fallback = fallback or DeterministicDecisionProvider()

    def route(self, query: str) -> RouteDecision:
        if self.primary is not None:
            try:
                return self.primary.route(query)
            except JevProviderError:
                pass
        return self.fallback.route(query)

    def evaluate_coverage(
        self, query: str, facets: list[str], evidence: list[EvidencePacket]
    ) -> CoverageDecision:
        if self.primary is not None:
            try:
                return self.primary.evaluate_coverage(query, facets, evidence)
            except JevProviderError:
                pass
        return self.fallback.evaluate_coverage(query, facets, evidence)

    def evaluate_claim(self, claim: str, evidence: list[EvidencePacket]) -> ClaimDecision:
        # Exact deterministic guards run before any semantic checker. A remote/model
        # assessment is never allowed to upgrade a known numeric/unit/polarity mismatch.
        screened = self.fallback.evaluate_claim(claim, evidence)
        if (
            screened.assessment_state.value == "deterministic_exact"
            and screened.verdict in {ClaimVerdict.CONFLICTING, ClaimVerdict.INSUFFICIENT}
        ):
            return screened
        if self.primary is not None:
            try:
                return self.primary.evaluate_claim(claim, evidence)
            except JevProviderError:
                pass
        return screened

    def close(self) -> None:
        for provider in (self.primary, self.fallback):
            close = getattr(provider, "close", None)
            if callable(close):
                close()
