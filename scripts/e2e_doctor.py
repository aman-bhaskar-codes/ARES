from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

import connectivity_doctor
from ares.api.settings import Settings

def main() -> int:
    parser = argparse.ArgumentParser(description="ARES One-Command E2E Doctor")
    parser.add_argument('--env-file', default='.env', help='environment file')
    parser.add_argument('--base-url', default=os.getenv('ARES_API_URL', 'http://127.0.0.1:8000'))
    parser.add_argument('--live-gemini', action='store_true', help='Explicitly opt-in to spend money on live Gemini calls')
    parser.add_argument('--timeout', type=int, default=90)
    args = parser.parse_args()

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"[FAIL] environment file not found: {env_path}")
        return 2

    try:
        settings = Settings(_env_file=env_path)  # type: ignore
        settings.validate_live_mode()
    except Exception as exc:
        print(f"[FAIL] settings: {type(exc).__name__}: {exc}")
        return 2

    print("--- 1. CONFIG & DB CHECKS ---")
    static = connectivity_doctor._static_checks(settings)
    db = connectivity_doctor._db_check(settings)
    for res in static + [db]:
        connectivity_doctor._print(res)
        if res.required and not res.ok:
            return 1
    
    if not args.live_gemini:
        print("\n[SKIP] Skipping live E2E run. Use --live-gemini to explicitly opt-in to Gemini calls and run full flow.")
        return 0

    print("\n--- 2. API & RUN PIPELINE ---")
    base = args.base_url.rstrip('/')
    with httpx.Client(base_url=base, timeout=10) as client:
        try:
            status = client.get('/api/v1/system/status').raise_for_status().json()
            print("[OK] API responded to /system/status")
        except Exception as exc:
            print(f"[FAIL] API is unreachable: {exc}")
            return 1
            
        conversation = client.post('/api/v1/conversations', json={'title': 'E2E Doctor Run'}).raise_for_status().json()
        print(f"[OK] Created conversation {conversation['id']}")
        
        run = client.post(
            '/api/v1/runs',
            headers={'Idempotency-Key': f'e2e-doctor-{uuid4()}'},
            json={
                'conversation_id': conversation['id'],
                'query': 'What is the speed of light in vacuum?',
                'mode': 'quick',
                'source_scope': ['web'],
                'document_ids': [],
            },
        ).raise_for_status().json()
        print(f"[OK] Queued run {run['id']}")

        deadline = time.monotonic() + args.timeout
        last_status = None
        while time.monotonic() < deadline:
            run = client.get(f"/api/v1/runs/{run['id']}").raise_for_status().json()
            if run['status'] != last_status:
                print(f"     ... status changed to: {run['status']}")
                last_status = run['status']
            if run['status'] in {'completed', 'partial', 'failed', 'cancelled'}:
                break
            time.sleep(1)
        else:
            print('[FAIL] Timed out waiting for worker.')
            return 1

        if run['status'] != 'completed':
            print(f"[FAIL] Run ended as {run['status']}: {run.get('error_code')} {run.get('error_message')}")
            return 1
            
        block = run['answer_blocks'][0]
        claims = len(block['claims'])
        citations = len(block['citations'])
        print(f"[OK] Run completed with {claims} claims and {citations} citations")
        if not claims or not citations:
            print('[FAIL] No inspectable citations generated.')
            return 1
            
        print("\n[SUCCESS] E2E pipeline is healthy (config -> DB -> API -> worker -> provider -> Gemini -> final run).")
        return 0

if __name__ == '__main__':
    raise SystemExit(main())
