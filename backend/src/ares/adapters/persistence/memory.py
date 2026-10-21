from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import UUID

from ares.adapters.db import MemoryEpisodeRow, MemoryFactRow, MemoryPreferenceRow
from ares.adapters.persistence.base import SqlRepositoryBase
from ares.domain.memory import (
    EpisodeCreate,
    FactCreate,
    MemoryEpisode,
    MemoryFact,
    MemoryPreference,
    PreferenceUpdate,
)
from sqlalchemy import delete, select, text


class SqlMemoryRepository(SqlRepositoryBase):
    @staticmethod
    def _episode_model(row: MemoryEpisodeRow) -> MemoryEpisode:
        return MemoryEpisode(
            id=row.id,
            workspace_id=row.workspace_id,
            user_id=row.user_id,
            conversation_id=row.conversation_id,
            run_id=row.run_id,
            title=row.title,
            summary=row.summary,
            key_findings=list(row.key_findings or []),
            importance=float(row.importance),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _fact_model(row: MemoryFactRow) -> MemoryFact:
        return MemoryFact(
            id=row.id,
            workspace_id=row.workspace_id,
            user_id=row.user_id,
            subject=row.subject,
            predicate=row.predicate,
            fact=row.fact,
            evidence_source=row.evidence_source,
            confidence=float(row.confidence),
            status=row.status,  # type: ignore[arg-type]
            superseded_by_id=row.superseded_by_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _preference_model(row: MemoryPreferenceRow) -> MemoryPreference:
        return MemoryPreference(
            id=row.id,
            workspace_id=row.workspace_id,
            user_id=row.user_id,
            depth=row.depth,  # type: ignore[arg-type]
            preferred_domains=list(row.preferred_domains or []),
            excluded_domains=list(row.excluded_domains or []),
            tone=row.tone,  # type: ignore[arg-type]
            custom_instructions=row.custom_instructions,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    # --- Episodes ---

    def create_memory_episode(
        self,
        workspace_id: UUID,
        user_id: UUID,
        payload: EpisodeCreate,
    ) -> MemoryEpisode:
        with self._sessions.begin() as session:
            row = MemoryEpisodeRow(
                workspace_id=workspace_id,
                user_id=user_id,
                conversation_id=payload.conversation_id,
                run_id=payload.run_id,
                title=payload.title.strip(),
                summary=payload.summary.strip(),
                key_findings=payload.key_findings,
                importance=payload.importance,
            )
            session.add(row)
            session.flush()
            return self._episode_model(row)

    def list_memory_episodes(
        self,
        workspace_id: UUID,
        *,
        limit: int = 50,
    ) -> list[MemoryEpisode]:
        with self._sessions() as session:
            rows = session.scalars(
                select(MemoryEpisodeRow)
                .where(MemoryEpisodeRow.workspace_id == workspace_id)
                .order_by(MemoryEpisodeRow.created_at.desc())
                .limit(limit)
            ).all()
            return [self._episode_model(r) for r in rows]

    def get_memory_episode(
        self,
        episode_id: UUID,
        workspace_id: UUID,
    ) -> MemoryEpisode | None:
        with self._sessions() as session:
            row = session.scalar(
                select(MemoryEpisodeRow).where(
                    MemoryEpisodeRow.id == episode_id,
                    MemoryEpisodeRow.workspace_id == workspace_id,
                )
            )
            return self._episode_model(row) if row is not None else None

    def delete_memory_episode(
        self,
        episode_id: UUID,
        workspace_id: UUID,
    ) -> bool:
        with self._sessions.begin() as session:
            result = session.execute(
                delete(MemoryEpisodeRow).where(
                    MemoryEpisodeRow.id == episode_id,
                    MemoryEpisodeRow.workspace_id == workspace_id,
                )
            )
            return bool(result.rowcount > 0)

    def search_memory_episodes(
        self,
        workspace_id: UUID,
        query: str,
        *,
        limit: int = 10,
        half_life_days: float = 14.0,
    ) -> list[tuple[MemoryEpisode, float]]:
        """Search episodes combining lexical relevance with exponential recency decay and importance."""
        if not query.strip():
            return []
        engine = self._sessions.kw.get("bind")
        dialect = engine.dialect.name if engine is not None else "unknown"
        terms = [t.casefold() for t in query.replace("-", " ").split() if len(t) > 1]
        if not terms:
            return []

        now = datetime.now(UTC)
        decay_constant = math.log(2) / max(0.1, half_life_days)

        with self._sessions() as session:
            if dialect == "postgresql":
                # PostgreSQL path using to_tsvector + ts_rank_cd
                raw_rows = session.execute(
                    text(
                        """
                        SELECT id,
                               ts_rank_cd(
                                   to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(cast(key_findings as text), '')),
                                   websearch_to_tsquery('simple', :query)
                               ) AS rank
                        FROM memory_episodes
                        WHERE workspace_id = :workspace_id
                          AND to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(cast(key_findings as text), ''))
                              @@ websearch_to_tsquery('simple', :query)
                        ORDER BY rank DESC
                        LIMIT 100
                        """
                    ),
                    {"workspace_id": workspace_id, "query": query},
                ).all()
                if not raw_rows:
                    return []
                ids = [UUID(str(r[0])) for r in raw_rows]
                rank_map = {UUID(str(r[0])): float(r[1]) for r in raw_rows}
                rows = session.scalars(
                    select(MemoryEpisodeRow).where(MemoryEpisodeRow.id.in_(ids))
                ).all()
            else:
                # Deterministic SQLite / test fallback
                rows = session.scalars(
                    select(MemoryEpisodeRow).where(MemoryEpisodeRow.workspace_id == workspace_id)
                ).all()
                rank_map = {}
                for r in rows:
                    findings_text = " ".join(r.key_findings) if isinstance(r.key_findings, list) else ""
                    combined = f"{r.title} {r.summary} {findings_text}".casefold()
                    score = sum(combined.count(term) for term in terms)
                    phrase = " ".join(terms[:8])
                    if phrase and phrase in combined:
                        score += 3.0
                    if score > 0:
                        rank_map[r.id] = float(score)

            scored: list[tuple[MemoryEpisode, float]] = []
            for r in rows:
                base_score = rank_map.get(r.id, 0.0)
                if base_score <= 0.0:
                    continue
                dt_days = max(0.0, (now - r.created_at.replace(tzinfo=UTC)).total_seconds() / 86400.0)
                recency_weight = math.exp(-decay_constant * dt_days)
                importance_factor = 1.0 + 0.5 * float(r.importance)
                final_score = base_score * recency_weight * importance_factor
                scored.append((self._episode_model(r), final_score))

            scored.sort(key=lambda pair: pair[1], reverse=True)
            return scored[:limit]

    # --- Facts ---

    def create_memory_fact(
        self,
        workspace_id: UUID,
        user_id: UUID,
        payload: FactCreate,
    ) -> MemoryFact:
        with self._sessions.begin() as session:
            # If superseded_by_id is provided, link it
            row = MemoryFactRow(
                workspace_id=workspace_id,
                user_id=user_id,
                subject=payload.subject.strip(),
                predicate=payload.predicate.strip(),
                fact=payload.fact.strip(),
                evidence_source=payload.evidence_source,
                confidence=payload.confidence,
                status="active",
                superseded_by_id=payload.superseded_by_id,
            )
            session.add(row)
            session.flush()
            return self._fact_model(row)

    def list_memory_facts(
        self,
        workspace_id: UUID,
        *,
        subject: str | None = None,
        status: str = "active",
        limit: int = 100,
    ) -> list[MemoryFact]:
        with self._sessions() as session:
            stmt = select(MemoryFactRow).where(
                MemoryFactRow.workspace_id == workspace_id,
            )
            if status != "all":
                stmt = stmt.where(MemoryFactRow.status == status)
            if subject is not None and subject.strip():
                stmt = stmt.where(MemoryFactRow.subject.ilike(f"%{subject.strip()}%"))
            rows = session.scalars(stmt.order_by(MemoryFactRow.created_at.desc()).limit(limit)).all()
            return [self._fact_model(r) for r in rows]

    def get_memory_fact(
        self,
        fact_id: UUID,
        workspace_id: UUID,
    ) -> MemoryFact | None:
        with self._sessions() as session:
            row = session.scalar(
                select(MemoryFactRow).where(
                    MemoryFactRow.id == fact_id,
                    MemoryFactRow.workspace_id == workspace_id,
                )
            )
            return self._fact_model(row) if row is not None else None

    def delete_memory_fact(
        self,
        fact_id: UUID,
        workspace_id: UUID,
    ) -> bool:
        with self._sessions.begin() as session:
            result = session.execute(
                delete(MemoryFactRow).where(
                    MemoryFactRow.id == fact_id,
                    MemoryFactRow.workspace_id == workspace_id,
                )
            )
            return bool(result.rowcount > 0)

    def supersede_memory_fact(
        self,
        old_fact_id: UUID,
        new_fact_id: UUID,
        workspace_id: UUID,
    ) -> bool:
        with self._sessions.begin() as session:
            old_row = session.scalar(
                select(MemoryFactRow).where(
                    MemoryFactRow.id == old_fact_id,
                    MemoryFactRow.workspace_id == workspace_id,
                )
            )
            if old_row is None:
                return False
            old_row.status = "superseded"
            old_row.superseded_by_id = new_fact_id
            old_row.updated_at = datetime.now(UTC)
            return True

    def search_memory_facts(
        self,
        workspace_id: UUID,
        query: str,
        *,
        limit: int = 20,
    ) -> list[tuple[MemoryFact, float]]:
        if not query.strip():
            return []
        terms = [t.casefold() for t in query.replace("-", " ").split() if len(t) > 1]
        if not terms:
            return []

        with self._sessions() as session:
            rows = session.scalars(
                select(MemoryFactRow).where(
                    MemoryFactRow.workspace_id == workspace_id,
                    MemoryFactRow.status == "active",
                )
            ).all()

            scored: list[tuple[MemoryFact, float]] = []
            for r in rows:
                full_text = f"{r.subject} {r.predicate} {r.fact}".casefold()
                score = sum(full_text.count(term) for term in terms)
                phrase = " ".join(terms[:8])
                if phrase and phrase in full_text:
                    score += 2.0
                if score > 0:
                    scored.append((self._fact_model(r), float(score) * float(r.confidence)))

            scored.sort(key=lambda pair: pair[1], reverse=True)
            return scored[:limit]

    def consolidate_memory_facts(
        self,
        workspace_id: UUID,
    ) -> dict[str, int]:
        """Consolidate active facts, auto-resolving direct predicate contradictions by recency."""
        with self._sessions.begin() as session:
            active_rows = session.scalars(
                select(MemoryFactRow).where(
                    MemoryFactRow.workspace_id == workspace_id,
                    MemoryFactRow.status == "active",
                ).order_by(MemoryFactRow.created_at.desc())
            ).all()

            grouped: dict[tuple[str, str], list[MemoryFactRow]] = {}
            for r in active_rows:
                key = (r.subject.strip().casefold(), r.predicate.strip().casefold())
                grouped.setdefault(key, []).append(r)

            superseded_count = 0
            for _key, rows in grouped.items():
                if len(rows) <= 1:
                    continue
                # Keep latest active, supersede older conflicting statements
                latest = rows[0]
                for older in rows[1:]:
                    older.status = "superseded"
                    older.superseded_by_id = latest.id
                    older.updated_at = datetime.now(UTC)
                    superseded_count += 1

            total_active = len(active_rows) - superseded_count
            return {
                "active_facts": total_active,
                "superseded_facts": superseded_count,
            }

    # --- Preferences ---

    def get_memory_preferences(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> MemoryPreference:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(MemoryPreferenceRow).where(
                    MemoryPreferenceRow.workspace_id == workspace_id,
                    MemoryPreferenceRow.user_id == user_id,
                )
            )
            if row is None:
                row = MemoryPreferenceRow(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    depth="standard",
                    preferred_domains=[],
                    excluded_domains=[],
                    tone="academic",
                    custom_instructions=None,
                )
                session.add(row)
                session.flush()
            return self._preference_model(row)

    def update_memory_preferences(
        self,
        workspace_id: UUID,
        user_id: UUID,
        payload: PreferenceUpdate,
    ) -> MemoryPreference:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(MemoryPreferenceRow).where(
                    MemoryPreferenceRow.workspace_id == workspace_id,
                    MemoryPreferenceRow.user_id == user_id,
                )
            )
            if row is None:
                row = MemoryPreferenceRow(
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
                session.add(row)

            if payload.depth is not None:
                row.depth = payload.depth
            if payload.preferred_domains is not None:
                row.preferred_domains = payload.preferred_domains
            if payload.excluded_domains is not None:
                row.excluded_domains = payload.excluded_domains
            if payload.tone is not None:
                row.tone = payload.tone
            if payload.custom_instructions is not None:
                row.custom_instructions = payload.custom_instructions
            row.updated_at = datetime.now(UTC)
            session.flush()
            return self._preference_model(row)
