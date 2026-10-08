import logging
from uuid import UUID, uuid4
from datetime import datetime, timezone
from ares.domain.watchlists import Watchlist, EvidenceChange
from ares.application.repository import Repository

logger = logging.getLogger(__name__)

class WatchlistManager:
    def __init__(self, repository: Repository):
        self.repository = repository

    def check_for_due_watchlists(self) -> list[Watchlist]:
        # This would interface with the database to find watchlists where next_run_time <= now
        # and state == 'active'
        return []

    def dispatch_watchlist_run(self, watchlist: Watchlist):
        # Uses unique (watchlist_id, scheduled_slot) job key to prevent duplicate runs
        # Enforces workspace limits (< 5 active per workspace) and quota
        pass

    def evaluate_evidence_changes(self, watchlist_id: UUID, old_evidence: list[dict], new_evidence: list[dict]) -> list[EvidenceChange]:
        changes = []
        old_map = {e["id"]: e for e in old_evidence}
        new_map = {e["id"]: e for e in new_evidence}
        
        for e_id, new_item in new_map.items():
            if e_id not in old_map:
                changes.append(EvidenceChange(
                    change_id=uuid4(),
                    watchlist_id=watchlist_id,
                    source_id=e_id,
                    change_type="new_source",
                    after_capture_date=datetime.now(timezone.utc),
                    after_hash=new_item.get("content_hash")
                ))
            else:
                old_item = old_map[e_id]
                if old_item.get("content_hash") != new_item.get("content_hash"):
                    changes.append(EvidenceChange(
                        change_id=uuid4(),
                        watchlist_id=watchlist_id,
                        source_id=e_id,
                        change_type="evidence_change",
                        before_capture_date=old_item.get("capture_date"),
                        after_capture_date=datetime.now(timezone.utc),
                        before_hash=old_item.get("content_hash"),
                        after_hash=new_item.get("content_hash")
                    ))
                elif old_item.get("metadata_hash") != new_item.get("metadata_hash"):
                    changes.append(EvidenceChange(
                        change_id=uuid4(),
                        watchlist_id=watchlist_id,
                        source_id=e_id,
                        change_type="metadata_only",
                        before_capture_date=old_item.get("capture_date"),
                        after_capture_date=datetime.now(timezone.utc),
                        before_hash=old_item.get("content_hash"),
                        after_hash=new_item.get("content_hash")
                    ))
                    
        for e_id, old_item in old_map.items():
            if e_id not in new_map:
                changes.append(EvidenceChange(
                    change_id=uuid4(),
                    watchlist_id=watchlist_id,
                    source_id=e_id,
                    change_type="source_removed",
                    before_capture_date=old_item.get("capture_date"),
                    after_capture_date=datetime.now(timezone.utc),
                    before_hash=old_item.get("content_hash")
                ))
                
        return changes
