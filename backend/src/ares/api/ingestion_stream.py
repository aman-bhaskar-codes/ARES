from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request

from ares.application.identity import Principal, principal_scope
from ares.application.repository import NotFoundError, Repository
from ares.domain.assets import IngestionEventEnvelope


def _wire(item: IngestionEventEnvelope, *, named: bool) -> str:
    event_line = f"event: {item.event_type}\n" if named else ""
    return f"id: {item.seq}\n{event_line}data: {item.model_dump_json()}\n\n"


async def stream_ingestion_events(
    *,
    repository: Repository,
    ingestion_id: UUID,
    request: Request,
    principal: Principal | None,
    after: int,
    revalidate: Callable[[], bool],
    page_size: int,
    max_replay: int,
    heartbeat_seconds: float,
    authorization_recheck_seconds: float,
) -> AsyncIterator[str]:
    def scoped(call):
        if principal is None:
            return call()
        with principal_scope(principal):
            return call()

    snapshot = await asyncio.to_thread(lambda: scoped(lambda: repository.get_ingestion(ingestion_id)))
    cursor = max(0, after)
    if snapshot.last_seq - cursor > max_replay:
        synthetic = IngestionEventEnvelope(
            ingestion_id=ingestion_id,
            seq=snapshot.last_seq,
            event_type="stream.snapshot_required",
            at=datetime.now(UTC),
            payload={"last_seq": snapshot.last_seq, "requested_after": cursor},
        )
        yield _wire(synthetic, named=False)
        cursor = snapshot.last_seq
        if snapshot.status.terminal:
            return
    if snapshot.status.terminal and cursor >= snapshot.last_seq:
        return

    loop = asyncio.get_running_loop()
    last_heartbeat = last_auth = loop.time()
    delay = 0.25
    while True:
        if await request.is_disconnected():
            return
        now = loop.time()
        if now - last_auth >= authorization_recheck_seconds:
            if not await asyncio.to_thread(revalidate):
                return
            last_auth = now
        try:
            items = await asyncio.to_thread(
                lambda: scoped(lambda: repository.list_ingestion_events(ingestion_id, after=cursor, limit=page_size))
            )
        except NotFoundError:
            return
        if items:
            delay = 0.25
            last_heartbeat = now
            for item in items:
                cursor = max(cursor, item.seq)
                yield _wire(item, named=True)
                yield _wire(item, named=False)
            latest = await asyncio.to_thread(lambda: scoped(lambda: repository.get_ingestion(ingestion_id)))
            if latest.status.terminal and cursor >= latest.last_seq:
                return
            continue
        if now - last_heartbeat >= heartbeat_seconds:
            yield ": heartbeat\n\n"
            last_heartbeat = now
        await asyncio.sleep(delay)
        delay = min(2.0, delay * 1.5)
