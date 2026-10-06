from __future__ import annotations

import argparse
import os
import sys
import time
from uuid import uuid4

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one explicit live ARES research smoke through the public API."
    )
    parser.add_argument("query", nargs="?", default="What is the latest stable Gemini Flash model?")
    parser.add_argument("--base-url", default=os.getenv("ARES_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    with httpx.Client(base_url=base, timeout=10) as client:
        status = client.get("/api/v1/system/status").raise_for_status().json()
        if status.get("mode") != "local_live":
            print("Refusing smoke: API is not in local_live mode.", file=sys.stderr)
            return 2
        conversation = (
            client.post("/api/v1/conversations", json={"title": "Live smoke"})
            .raise_for_status()
            .json()
        )
        run = (
            client.post(
                "/api/v1/runs",
                headers={"Idempotency-Key": f"live-smoke-{uuid4()}"},
                json={
                    "conversation_id": conversation["id"],
                    "query": args.query,
                    "mode": "quick",
                    "source_scope": ["web"],
                    "document_ids": [],
                },
            )
            .raise_for_status()
            .json()
        )
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            run = client.get(f"/api/v1/runs/{run['id']}").raise_for_status().json()
            print(f"status={run['status']}")
            if run["status"] in {"completed", "partial", "failed", "cancelled"}:
                break
            time.sleep(1)
        else:
            print("Timed out waiting for worker. Is `make worker` running?", file=sys.stderr)
            return 3

        if run["status"] != "completed":
            print(
                f"Live smoke ended as {run['status']}: {run.get('error_code')} {run.get('error_message')}"
            )
            return 4
        block = run["answer_blocks"][0]
        print(f"completed claims={len(block['claims'])} citations={len(block['citations'])}")
        if not block["claims"] or not block["citations"]:
            print("Completed run has no inspectable citations.", file=sys.stderr)
            return 5
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
