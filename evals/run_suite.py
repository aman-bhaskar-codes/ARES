from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from dataclasses import asdict
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from ares.adapters.gemini_embeddings import GeminiEmbeddingProvider
from ares.adapters.jev import JevConfig, JevDecisionProvider
from ares.application.decisions import DeterministicDecisionProvider
from ares.application.rag import HybridRAGRetriever, RAGConfig
from ares.application.security import RemoteContentRiskScanner
from ares.domain.models import FetchedDocument
from ares.domain.research import EvidencePacket
from ares.evaluation.metrics import aggregate_retrieval, classification_metrics, detection_metrics, retrieval_metrics

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "datasets"


def _decision_provider(name: str):
    if name == "deterministic":
        return DeterministicDecisionProvider()
    key = os.getenv("JEV_API_KEY", "").strip()
    if not key:
        raise SystemExit("JEV_API_KEY is required for --decision-provider jev; there is no automatic metered fallback")
    return JevDecisionProvider(JevConfig(api_key=key, model=os.getenv("JEV_MODEL", "jev-latest")))


def routing(provider_name: str, data_dir: Path = DATA, dataset_kind: str = "development_regression") -> dict[str, object]:
    cases = json.loads((data_dir / "routing_cases.json").read_text())
    provider = _decision_provider(provider_name)
    results = []
    expected: list[str] = []
    predicted: list[str] = []
    confidences: list[float] = []
    try:
        for case in cases:
            decision = provider.route(case["query"])
            expected.append(case["expected_task"])
            predicted.append(decision.task.value)
            confidences.append(decision.confidence)
            results.append({"query": case["query"], "expected": case["expected_task"], "actual": decision.task.value, "confidence": decision.confidence, "provider": decision.provider})
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    metrics = classification_metrics(expected, predicted, confidences=confidences)
    return {"suite": "routing", "provider": provider_name, "dataset_kind": dataset_kind, "metrics": asdict(metrics), "results": results}


def claims(provider_name: str, data_dir: Path = DATA, dataset_kind: str = "development_regression") -> dict[str, object]:
    cases = json.loads((data_dir / "claim_cases.json").read_text())
    provider = _decision_provider(provider_name)
    expected: list[str] = []
    predicted: list[str] = []
    confidences: list[float] = []
    results = []
    try:
        for case_index, case in enumerate(cases):
            packets = [
                EvidencePacket(
                    evidence_id=uuid5(NAMESPACE_URL, f"claim:{case_index}:{idx}:evidence"),
                    source_id=uuid5(NAMESPACE_URL, f"claim:{case_index}:{idx}:source"),
                    title=f"fixture-{idx}", url=f"https://fixture.example/{case_index}/{idx}", domain="fixture.example",
                    text=text, locator=f"fixture {idx}", captured_at=datetime.now(UTC), content_hash=(f"{case_index}{idx}" * 64)[:64],
                )
                for idx, text in enumerate(case["evidence"])
            ]
            decision = provider.evaluate_claim(case["claim"], packets)
            expected.append(case["expected_verdict"])
            predicted.append(decision.verdict.value)
            confidences.append(decision.confidence)
            results.append({"claim": case["claim"], "expected": case["expected_verdict"], "actual": decision.verdict.value, "confidence": decision.confidence, "provider": decision.provider})
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    metrics = classification_metrics(expected, predicted, confidences=confidences)
    insufficient_total = sum(value == "insufficient_evidence" for value in expected)
    unsupported_retained = sum(
        exp == "insufficient_evidence" and pred != "insufficient_evidence"
        for exp, pred in zip(expected, predicted, strict=True)
    )
    retained = [
        (exp, pred) for exp, pred in zip(expected, predicted, strict=True)
        if pred != "insufficient_evidence"
    ]
    retained_correctly_qualified = sum(exp != "insufficient_evidence" for exp, _ in retained)
    conflict_total = sum(value == "conflicting" for value in expected)
    conflict_found = sum(
        exp == "conflicting" and pred == "conflicting"
        for exp, pred in zip(expected, predicted, strict=True)
    )
    claim_quality = {
        "unsupported_claim_retention_rate": unsupported_retained / insufficient_total if insufficient_total else 0.0,
        "retained_claim_precision": retained_correctly_qualified / len(retained) if retained else 1.0,
        "conflict_recall": conflict_found / conflict_total if conflict_total else 1.0,
    }
    metric_payload = asdict(metrics)
    metric_payload.update(claim_quality)
    return {"suite": "claims", "provider": provider_name, "dataset_kind": dataset_kind, "metrics": metric_payload, "results": results}


def retrieval(mode: str, embedding_provider: str, data_dir: Path = DATA, dataset_kind: str = "development_regression") -> dict[str, object]:
    embedder = None
    if embedding_provider == "gemini":
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            raise SystemExit("GEMINI_API_KEY is required for live embedding ablation")
        embedder = GeminiEmbeddingProvider(
            key,
            model=os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2"),
            dimensions=int(os.getenv("GEMINI_EMBEDDING_DIMENSIONS", "768")),
        )
    elif mode in {"semantic", "hybrid"}:
        raise SystemExit("semantic/hybrid evaluation requires --embedding-provider gemini; lexical is the offline gate")

    cases = json.loads((data_dir / "retrieval_cases.json").read_text())
    per_case = []
    details = []
    try:
        for case_index, case in enumerate(cases):
            source_to_id: dict[str, str] = {}
            docs = []
            for doc in case["documents"]:
                source_id = uuid5(NAMESPACE_URL, f"retrieval:{case_index}:{doc['id']}")
                source_to_id[str(source_id)] = doc["id"]
                docs.append(FetchedDocument(
                    source_id=source_id, title=doc["title"], url=f"https://fixture.example/{case_index}/{doc['id']}",
                    final_url=f"https://fixture.example/{case_index}/{doc['id']}", text=doc["text"],
                    content_hash=(doc["id"].encode().hex() + "0" * 64)[:64], extraction_method="fixture", byte_count=len(doc["text"].encode()),
                ))
            retriever = HybridRAGRetriever(config=RAGConfig(mode=mode, target_chars=800, min_chunk_chars=80, max_chunks_per_source=1), embedder=embedder)
            result = retriever.retrieve_with_trace(case["query"], docs, limit=5)
            ranked_ids = [source_to_id[str(item.source_id)] for item in result.candidates]
            metric = retrieval_metrics(ranked_ids, set(case["relevant_ids"]), k=5)
            per_case.append(metric)
            details.append({"query": case["query"], "relevant_ids": case["relevant_ids"], "ranked_ids": ranked_ids, "mode": result.mode, "metrics": asdict(metric)})
    finally:
        close = getattr(embedder, "close", None)
        if callable(close):
            close()
    return {"suite": "retrieval", "provider": embedding_provider, "mode": mode, "dataset_kind": dataset_kind, "metrics": aggregate_retrieval(per_case), "results": details}


def security(data_dir: Path = DATA, dataset_kind: str = "development_regression") -> dict[str, object]:
    cases = json.loads((data_dir / "security_cases.json").read_text())
    scanner = RemoteContentRiskScanner()
    expected = []
    predicted = []
    details = []
    for case in cases:
        result = scanner.inspect(case["text"])
        expected.append(bool(case["risk"]))
        predicted.append(result.suspicious)
        details.append({"text": case["text"], "expected_risk": bool(case["risk"]), "predicted_risk": result.suspicious, "score": result.score, "categories": list(result.categories)})
    metrics = detection_metrics(expected, predicted)
    return {"suite": "security", "provider": "deterministic-observability-scanner", "dataset_kind": dataset_kind, "metrics": asdict(metrics), "results": details}


def _gate(report: dict[str, object]) -> tuple[bool, list[str]]:
    suite = report["suite"]
    metrics = report["metrics"]
    failures = []
    if suite == "routing":
        if metrics["macro_f1"] < 0.80: failures.append("routing macro_f1 < 0.80")
    elif suite == "claims":
        if metrics["macro_f1"] < 0.60: failures.append("claim macro_f1 < 0.60")
        if metrics["unsupported_claim_retention_rate"] > 0.10:
            failures.append("unsupported claim retention rate > 0.10")
        if metrics["conflict_recall"] < 0.70:
            failures.append("claim conflict recall < 0.70")
    elif suite == "retrieval":
        if metrics["recall_at_k"] < 0.80: failures.append("retrieval mean recall@5 < 0.80")
        if metrics["reciprocal_rank"] < 0.75: failures.append("retrieval mean reciprocal rank < 0.75")
    elif suite == "security":
        if metrics["true_positive_rate"] < 0.80: failures.append("security fixture TPR < 0.80")
        if metrics["false_positive_rate"] > 0.25: failures.append("security fixture FPR > 0.25")
    return not failures, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen ARES regression evaluation suites")
    parser.add_argument("--suite", choices=["routing", "claims", "retrieval", "security", "all"], default="all")
    parser.add_argument("--decision-provider", choices=["deterministic", "jev"], default="deterministic")
    parser.add_argument("--retrieval-mode", choices=["lexical", "semantic", "hybrid"], default="lexical")
    parser.add_argument("--embedding-provider", choices=["none", "gemini"], default="none")
    parser.add_argument("--report", default="evals/reports/regression_latest.json")
    parser.add_argument("--dataset-dir", default=str(DATA), help="Directory containing the four evaluation JSON files")
    parser.add_argument("--dataset-kind", default="development_regression", help="Provenance label written into the report")
    parser.add_argument("--no-gate", action="store_true")
    args = parser.parse_args()

    data_dir = Path(args.dataset_dir).resolve()
    required = {"routing_cases.json", "claim_cases.json", "retrieval_cases.json", "security_cases.json"}
    missing = sorted(name for name in required if not (data_dir / name).is_file())
    if missing:
        raise SystemExit(f"evaluation dataset directory is incomplete: missing {', '.join(missing)}")

    names = [args.suite] if args.suite != "all" else ["routing", "claims", "retrieval", "security"]
    reports = []
    for name in names:
        if name == "routing": reports.append(routing(args.decision_provider, data_dir, args.dataset_kind))
        elif name == "claims": reports.append(claims(args.decision_provider, data_dir, args.dataset_kind))
        elif name == "retrieval": reports.append(retrieval(args.retrieval_mode, args.embedding_provider, data_dir, args.dataset_kind))
        elif name == "security": reports.append(security(data_dir, args.dataset_kind))

    gate_failures = []
    for report in reports:
        passed, failures = _gate(report)
        report["gate_passed"] = passed
        report["gate_failures"] = failures
        gate_failures.extend(f"{report['suite']}: {failure}" for failure in failures)
    output = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "important_limit": "Development regression fixtures are not an external benchmark or production-quality claim. A held-out label is credible only when dataset provenance is genuinely independent of tuning.",
        "reports": reports,
        "gate_passed": not gate_failures,
        "gate_failures": gate_failures,
    }
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"gate_passed": output["gate_passed"], "gate_failures": gate_failures, "suites": [{"suite": r["suite"], "metrics": r["metrics"]} for r in reports]}, indent=2))
    return 0 if args.no_gate or output["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
