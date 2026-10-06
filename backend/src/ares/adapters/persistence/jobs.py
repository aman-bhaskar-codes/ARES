from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select, text

from ares.adapters.db import (
    ConversationRow,
    JobRow,
    ResourceLeaseRow,
    RunEventRow,
    RunRow,
    UserDocumentRow,
    WorkspaceMembershipRow,
    WorkerInstanceRow,
)
from ares.domain.models import (
    ConversationView,
    RunCreate,
    RunSnapshot,
    RunStatus,
)
from ares.domain.budgets import BUDGETS, BUDGET_VERSION


from ares.ports.repositories import NotFoundError, IdempotencyConflictError, StaleLeaseError, QuotaExceededError, RunAdmissionError, RunBudgetExceededError, RunAuthorizationError, ResourceCapacityError, JobLease, ResourceLease, IngestionLease, IngestionPublication


def _hash_request(payload: RunCreate) -> str:
    encoded = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


from ares.adapters.persistence.base import SqlRepositoryBase


class SqlJobRepository(SqlRepositoryBase):
    def create_conversation(self, title: str | None = None) -> ConversationView:
        principal = self._request_principal()
        with self._sessions.begin() as session:
            self._ensure_local_identity(session, principal)
            row = ConversationRow(
                workspace_id=principal.workspace_id,
                created_by_user_id=principal.user_id,
                title=(title or "New research").strip() or "New research",
            )
            session.add(row)
            session.flush()
            return ConversationView.model_validate(row)

    def create_run(
        self,
        request: RunCreate,
        idempotency_key: str,
        *,
        max_active_runs: int | None = None,
        max_active_runs_per_workspace: int | None = None,
        max_active_runs_per_user: int | None = None,
    ) -> tuple[RunSnapshot, bool]:
        request_hash = _hash_request(request)
        principal = self._request_principal()
        scoped_key = hashlib.sha256(
            f"{principal.workspace_id}\0{idempotency_key}".encode("utf-8")
        ).hexdigest()
        with self._sessions.begin() as session:
            self._ensure_local_identity(session, principal)
            conversation = session.scalar(
                select(ConversationRow).where(
                    ConversationRow.id == request.conversation_id,
                    ConversationRow.workspace_id == principal.workspace_id,
                )
            )
            if conversation is None:
                raise NotFoundError("conversation not found")
            if request.document_ids:
                owned_documents = set(
                    session.scalars(
                        select(UserDocumentRow.id).where(
                            UserDocumentRow.id.in_(request.document_ids),
                            UserDocumentRow.workspace_id == principal.workspace_id,
                        )
                    ).all()
                )
                missing = [
                    document_id
                    for document_id in request.document_ids
                    if document_id not in owned_documents
                ]
                if missing:
                    raise NotFoundError(f"document not found: {missing[0]}")
            existing = session.scalar(
                select(RunRow).where(
                    RunRow.idempotency_key == scoped_key,
                    RunRow.workspace_id == principal.workspace_id,
                )
            )
            if existing:
                if existing.request_hash != request_hash:
                    raise IdempotencyConflictError(
                        "idempotency key reused with a different request"
                    )
                return self._snapshot(existing), False

            terminal = [
                RunStatus.COMPLETED.value,
                RunStatus.PARTIAL.value,
                RunStatus.FAILED.value,
                RunStatus.CANCELLED.value,
            ]
            if any(
                v is not None
                for v in (max_active_runs, max_active_runs_per_workspace, max_active_runs_per_user)
            ):
                if session.bind is not None and session.bind.dialect.name == "postgresql":
                    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 1095914835})
                if max_active_runs is not None:
                    if session.bind is not None and session.bind.dialect.name == "postgresql":
                        global_active = int(
                            session.scalar(text("SELECT ares_global_active_run_count()")) or 0
                        )
                    else:
                        global_active = int(
                            session.scalar(
                                select(func.count())
                                .select_from(RunRow)
                                .where(RunRow.status.not_in(terminal))
                            )
                            or 0
                        )
                    if global_active >= max_active_runs:
                        raise RunAdmissionError(
                            f"global active run limit reached ({max_active_runs})"
                        )
                if max_active_runs_per_workspace is not None:
                    workspace_active = int(
                        session.scalar(
                            select(func.count())
                            .select_from(RunRow)
                            .where(
                                RunRow.workspace_id == principal.workspace_id,
                                RunRow.status.not_in(terminal),
                            )
                        )
                        or 0
                    )
                    if workspace_active >= max_active_runs_per_workspace:
                        raise RunAdmissionError(
                            f"workspace active run limit reached ({max_active_runs_per_workspace})"
                        )
                if max_active_runs_per_user is not None:
                    user_active = int(
                        session.scalar(
                            select(func.count())
                            .select_from(RunRow)
                            .where(
                                RunRow.workspace_id == principal.workspace_id,
                                RunRow.created_by_user_id == principal.user_id,
                                RunRow.status.not_in(terminal),
                            )
                        )
                        or 0
                    )
                    if user_active >= max_active_runs_per_user:
                        raise RunAdmissionError(
                            f"user active run limit reached ({max_active_runs_per_user})"
                        )

            now = datetime.now(UTC)
            budget = BUDGETS[request.mode]
            run = RunRow(
                conversation_id=request.conversation_id,
                workspace_id=principal.workspace_id,
                created_by_user_id=principal.user_id,
                query=request.query,
                mode=request.mode.value,
                source_scope=list(request.source_scope),
                document_ids=[str(value) for value in request.document_ids],
                date_window=request.date_window.model_dump(mode="json")
                if request.date_window
                else None,
                deadline_at=now + timedelta(seconds=budget.wall_clock_seconds),
                budget_version=BUDGET_VERSION,
                usage_ledger={},
                last_seq=1,
                status=RunStatus.QUEUED.value,
                idempotency_key=scoped_key,
                request_hash=request_hash,
                created_at=now,
                updated_at=now,
            )
            session.add(run)
            session.flush()
            session.add(JobRow(run_id=run.id))
            session.add(
                RunEventRow(
                    run_id=run.id,
                    seq=1,
                    schema_version=2,
                    event_type="run.created",
                    payload={
                        "status": "queued",
                        "budget_version": BUDGET_VERSION,
                        "deadline_at": run.deadline_at.isoformat(),
                    },
                )
            )
            conversation.updated_at = datetime.now(UTC)
            session.flush()
            return self._snapshot(run), True

    def initialize_run_execution_contract(
        self, run_id: UUID, *, wall_clock_seconds: int, lease_token: UUID
    ) -> RunSnapshot:
        with self._sessions.begin() as session:
            self._require_lease(session, run_id, lease_token)
            row = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
            if row is None:
                raise NotFoundError("run not found")
            if row.deadline_at is None:
                row.deadline_at = datetime.now(UTC) + timedelta(seconds=wall_clock_seconds)
            if not row.budget_version or row.budget_version == "legacy":
                row.budget_version = BUDGET_VERSION
            if row.usage_ledger is None:
                row.usage_ledger = {}
            session.flush()
            return self._snapshot(row)

    def prepare_run_resume(self, lease: JobLease) -> None:
        if lease.attempt <= 1:
            return
        with self._sessions.begin() as session:
            self._require_lease(session, lease.run_id, lease.token)
            row = session.get(RunRow, lease.run_id)
            if row is None:
                raise NotFoundError("run not found")
            current = RunStatus(row.status)
            if current.terminal or current is RunStatus.QUEUED:
                return
            previous = current.value
            row.status = RunStatus.PLANNING.value
            self._append_event(
                session,
                lease.run_id,
                "run.resumed",
                {
                    "attempt": lease.attempt,
                    "previous_status": previous,
                    "status": RunStatus.PLANNING.value,
                },
            )

    def authorize_run_execution(self, run_id: UUID, *, lease_token: UUID) -> None:
        with self._sessions() as session:
            self._require_lease(session, run_id, lease_token)
            run = session.get(RunRow, run_id)
            if run is None:
                raise NotFoundError("run not found")
            membership = session.scalar(
                select(WorkspaceMembershipRow.id).where(
                    WorkspaceMembershipRow.workspace_id == run.workspace_id,
                    WorkspaceMembershipRow.user_id == run.created_by_user_id,
                )
            )
            if membership is None:
                raise RunAuthorizationError("run creator no longer has workspace access")
            ids = [UUID(value) for value in (run.document_ids or [])]
            if ids:
                owned = set(
                    session.scalars(
                        select(UserDocumentRow.id).where(
                            UserDocumentRow.id.in_(ids),
                            UserDocumentRow.workspace_id == run.workspace_id,
                        )
                    ).all()
                )
                missing = [value for value in ids if value not in owned]
                if missing:
                    raise RunAuthorizationError(f"document access revoked or deleted: {missing[0]}")

    def consume_run_usage(
        self, run_id: UUID, *, delta: dict[str, int], limits: dict[str, int], lease_token: UUID
    ) -> dict[str, int]:
        with self._sessions.begin() as session:
            self._require_lease(session, run_id, lease_token)
            row = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
            if row is None:
                raise NotFoundError("run not found")
            ledger = {str(k): int(v) for k, v in (row.usage_ledger or {}).items()}
            for key, amount in delta.items():
                if amount < 0:
                    raise ValueError("run usage deltas cannot be negative")
                candidate = ledger.get(key, 0) + int(amount)
                if key in limits and candidate > limits[key]:
                    raise RunBudgetExceededError(
                        f"run budget exhausted for {key}: {candidate} > {limits[key]}"
                    )
                ledger[key] = candidate
            row.usage_ledger = ledger
            session.flush()
            return dict(ledger)

    def claim_next_job(self, *, lease_seconds: int = 30, max_attempts: int = 3) -> JobLease | None:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        token = uuid4()
        with self._sessions.begin() as session:
            exhausted = session.scalars(
                select(JobRow)
                .where(
                    JobRow.attempts >= max_attempts,
                    or_(
                        JobRow.state == "queued",
                        (JobRow.state == "running") & (JobRow.leased_until < now),
                    ),
                )
                .with_for_update(skip_locked=True)
            ).all()
            for job in exhausted:
                job.state = "failed"
                job.leased_until = None
                job.lease_token = None
                run = session.get(RunRow, job.run_id)
                if run is not None and not RunStatus(run.status).terminal:
                    run.status = RunStatus.FAILED.value
                    run.error_code = "WORKER_RETRY_EXHAUSTED"
                    run.error_message = (
                        f"worker retry budget exhausted after {job.attempts} attempts"
                    )
                    self._append_event(
                        session,
                        run.id,
                        "run.failed",
                        {"code": "WORKER_RETRY_EXHAUSTED", "attempts": job.attempts},
                    )

            stmt = (
                select(JobRow)
                .where(
                    JobRow.available_at <= now,
                    or_(
                        JobRow.state == "queued",
                        (JobRow.state == "running") & (JobRow.leased_until < now),
                    ),
                    JobRow.attempts < max_attempts,
                )
                .order_by(JobRow.priority.asc(), JobRow.available_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            row = session.scalar(stmt)
            if row is None:
                return None
            row.state = "running"
            row.lease_token = token
            row.leased_until = expires
            row.attempts += 1
            self._append_event(
                session,
                row.run_id,
                "job.claimed",
                {"attempt": row.attempts, "lease_seconds": lease_seconds},
            )
            return JobLease(
                run_id=row.run_id, token=token, leased_until=expires, attempt=row.attempts
            )

    def record_event(
        self,
        run_id: UUID,
        event_type: str,
        payload: dict[str, object],
        *,
        lease_token: UUID | None = None,
    ) -> None:
        # Discovery tracks can emit events concurrently. The process-local lock makes the
        # SQLite demo path deterministic (SQLite ignores SELECT ... FOR UPDATE) while
        # PostgreSQL still provides the cross-process row lock in _append_event.
        with self._event_lock:
            with self._sessions.begin() as session:
                if lease_token is not None:
                    self._require_lease(session, run_id, lease_token)
                if self._run_row(session, run_id) is None:
                    raise NotFoundError("run not found")
                self._append_event(session, run_id, event_type, payload)

    def fail_run(
        self, run_id: UUID, code: str, message: str, *, lease_token: UUID | None = None
    ) -> None:
        with self._sessions.begin() as session:
            if lease_token is not None:
                self._require_lease(session, run_id, lease_token)
            row = self._run_row(session, run_id)
            if row is None:
                raise NotFoundError("run not found")
            if RunStatus(row.status).terminal:
                return
            row.error_code = code
            row.error_message = message[:2000]
            row.status = RunStatus.FAILED.value
            self._append_event(
                session, run_id, "run.failed", {"code": code, "message": message[:500]}
            )

    def acquire_resource_lease(
        self, run_id: UUID, *, resource_key: str, capacity: int, ttl_seconds: int, lease_token: UUID
    ) -> ResourceLease:
        if capacity < 1 or ttl_seconds < 1:
            raise ValueError("resource lease capacity and ttl must be positive")
        now = datetime.now(UTC)
        until = now + timedelta(seconds=ttl_seconds)
        with self._sessions.begin() as session:
            self._require_lease(session, run_id, lease_token)
            run = session.get(RunRow, run_id)
            if run is None:
                raise NotFoundError("run not found")
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                key = int.from_bytes(
                    hashlib.sha256(resource_key.encode()).digest()[:8], "big", signed=True
                )
                session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
            session.execute(
                delete(ResourceLeaseRow).where(
                    ResourceLeaseRow.resource_key == resource_key,
                    ResourceLeaseRow.leased_until <= now,
                )
            )
            occupied = set(
                session.scalars(
                    select(ResourceLeaseRow.slot).where(
                        ResourceLeaseRow.resource_key == resource_key
                    )
                ).all()
            )
            slot = next((value for value in range(capacity) if value not in occupied), None)
            if slot is None:
                raise ResourceCapacityError(f"resource capacity exhausted: {resource_key}")
            token = uuid4()
            session.add(
                ResourceLeaseRow(
                    workspace_id=run.workspace_id,
                    owner_run_id=run_id,
                    resource_key=resource_key,
                    slot=slot,
                    lease_token=token,
                    leased_until=until,
                    created_at=now,
                )
            )
            session.flush()
            return ResourceLease(
                run_id=run_id, resource_key=resource_key, slot=slot, token=token, leased_until=until
            )

    def release_resource_lease(self, resource: ResourceLease) -> None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(ResourceLeaseRow).where(
                    ResourceLeaseRow.lease_token == resource.token,
                    ResourceLeaseRow.owner_run_id == resource.run_id,
                )
            )
            if row is not None:
                session.delete(row)

    def register_worker(
        self, instance_name: str, *, capabilities: dict[str, object] | None = None
    ) -> UUID:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = WorkerInstanceRow(
                instance_name=instance_name[:160],
                state="active",
                started_at=now,
                last_seen_at=now,
                capabilities_json=dict(capabilities or {}),
            )
            session.add(row)
            session.flush()
            return row.id

    def heartbeat_worker(
        self,
        worker_id: UUID,
        *,
        state: str = "active",
        capabilities: dict[str, object] | None = None,
    ) -> None:
        with self._sessions.begin() as session:
            row = session.get(WorkerInstanceRow, worker_id)
            if row is None:
                raise NotFoundError("worker registration not found")
            row.state = state[:24]
            row.last_seen_at = datetime.now(UTC)
            if capabilities is not None:
                row.capabilities_json = dict(capabilities)

    def stop_worker(self, worker_id: UUID) -> None:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = session.get(WorkerInstanceRow, worker_id)
            if row is not None:
                row.state = "stopped"
                row.last_seen_at = now
                row.stopped_at = now

    def finish_job(self, lease: JobLease, *, final_state: str = "done") -> None:
        with self._sessions.begin() as session:
            row = self._require_lease(session, lease.run_id, lease.token)
            row.state = final_state
            row.leased_until = None
            row.lease_token = None
