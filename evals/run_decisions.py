from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ares.adapters.jev import JevConfig, JevDecisionProvider
from ares.application.decisions import DeterministicDecisionProvider


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate ARES routing decisions on frozen cases")
    parser.add_argument("--provider", choices=["deterministic", "jev"], default="deterministic")
    parser.add_argument("--dataset", default="evals/datasets/routing_cases.json")
    parser.add_argument("--report", default="evals/reports/routing_latest.json")
    args = parser.parse_args()

    if args.provider == "jev":
        key = os.environ.get("JEV_API_KEY", "").strip()
        if not key:
            raise SystemExit("JEV_API_KEY is required for --provider jev; no paid/metered fallback is automatic")
        provider = JevDecisionProvider(JevConfig(api_key=key, model=os.getenv("JEV_MODEL", "jev-latest")))
    else:
        provider = DeterministicDecisionProvider()

    cases = json.loads(Path(args.dataset).read_text())
    results = []
    correct = 0
    for case in cases:
        decision = provider.route(case["query"])
        match = decision.task.value == case["expected_task"]
        correct += int(match)
        results.append({
            "query": case["query"], "expected": case["expected_task"], "actual": decision.task.value,
            "provider": decision.provider, "confidence": decision.confidence, "correct": match,
        })
    report = {"provider": args.provider, "cases": len(cases), "correct": correct, "accuracy": correct / len(cases), "results": results}
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("provider", "cases", "correct", "accuracy")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
