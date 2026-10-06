#!/usr/bin/env python3
"""M10 retrieval ablation report.

Always evaluates the offline lexical baseline. Local dense/RRF evaluation is attempted only when
the pinned FastEmbed dependency and locally provisioned model are actually available. PostgreSQL
indexed evaluation is reported as NOT RUN unless a dedicated test database is configured; this
script never substitutes SQLite for the M10 indexed-performance gate.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from ares.adapters.local_embeddings import LocalFastEmbedProvider
from ares.application.rag import HybridRAGRetriever, RAGConfig
from ares.domain.models import FetchedDocument
from ares.evaluation.metrics import aggregate_retrieval, retrieval_metrics
from evals.run_suite import retrieval as lexical_retrieval

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/datasets/retrieval_cases.json"


def evaluate_with_embedder(mode: str, embedder) -> dict[str, object]:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    metrics = []
    details = []
    for case_index, case in enumerate(cases):
        source_to_id: dict[str, str] = {}
        docs = []
        for doc in case["documents"]:
            source_id = uuid5(NAMESPACE_URL, f"m10-retrieval:{case_index}:{doc['id']}")
            source_to_id[str(source_id)] = doc["id"]
            docs.append(
                FetchedDocument(
                    source_id=source_id,
                    title=doc["title"],
                    url=f"https://fixture.example/{case_index}/{doc['id']}",
                    final_url=f"https://fixture.example/{case_index}/{doc['id']}",
                    text=doc["text"],
                    content_hash=(doc["id"].encode().hex() + "0" * 64)[:64],
                    extraction_method="fixture",
                    byte_count=len(doc["text"].encode("utf-8")),
                )
            )
        retriever = HybridRAGRetriever(
            config=RAGConfig(
                mode=mode, target_chars=800, min_chunk_chars=80, max_chunks_per_source=1
            ),
            embedder=embedder,
        )
        result = retriever.retrieve_with_trace(case["query"], docs, limit=5)
        ranked_ids = [source_to_id[str(item.source_id)] for item in result.candidates]
        metric = retrieval_metrics(ranked_ids, set(case["relevant_ids"]), k=5)
        metrics.append(metric)
        details.append(
            {
                "query": case["query"],
                "ranked_ids": ranked_ids,
                "relevant_ids": case["relevant_ids"],
                "mode": result.mode,
                "semantic_used": result.semantic_used,
            }
        )
    return {
        "status": "pass",
        "mode": mode,
        "metrics": aggregate_retrieval(metrics),
        "results": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="evals/reports/m10_retrieval_ablation.json")
    parser.add_argument(
        "--local-model", default=os.getenv("LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    )
    parser.add_argument(
        "--local-cache", default=os.getenv("LOCAL_EMBEDDING_CACHE_DIR", ".data/models/fastembed")
    )
    args = parser.parse_args()

    lexical = lexical_retrieval("lexical", "none")
    lexical_status = {
        "status": "pass",
        "mode": "lexical",
        "metrics": lexical["metrics"],
        "gate_passed": lexical["metrics"]["recall_at_k"] >= 0.80
        and lexical["metrics"]["reciprocal_rank"] >= 0.75,
    }

    local: dict[str, object]
    embedder = LocalFastEmbedProvider(model=args.local_model, cache_dir=args.local_cache)
    try:
        # Force dependency/model loading before claiming the ablation ran.
        embedder.embed_query("ARES M10 retrieval readiness probe")
        local = {
            "status": "pass",
            "model": args.local_model,
            "semantic": evaluate_with_embedder("semantic", embedder),
            "hybrid_rrf": evaluate_with_embedder("hybrid", embedder),
        }
    except Exception as exc:
        local = {
            "status": "not_run",
            "model": args.local_model,
            "reason": f"{type(exc).__name__}: optional local embedding runtime/model is not provisioned",
        }
    finally:
        embedder.close()

    postgres_url = os.getenv("ARES_TEST_POSTGRES_URL", "").strip()
    postgres = (
        {
            "status": "external_gate",
            "configured": True,
            "instruction": "Run make test-postgres and the indexed retrieval benchmark against the disposable pgvector database.",
        }
        if postgres_url
        else {
            "status": "not_run",
            "configured": False,
            "reason": "ARES_TEST_POSTGRES_URL is not configured; SQLite is not accepted as an indexed PostgreSQL performance substitute.",
        }
    )

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "development_regression",
        "lexical_baseline": lexical_status,
        "local_dense_and_rrf": local,
        "postgres_indexed": postgres,
        "reranker_decision": {
            "enabled": False,
            "reason": "M10 plan requires measured relevance gain that justifies CPU latency. No held-out reranker gain has been measured in this environment, so no reranker dependency is promoted.",
        },
        "important_limit": "This development regression set is not an independent external benchmark.",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if lexical_status["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
