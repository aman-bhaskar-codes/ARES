from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID
from ares.application.repository import Repository


def checkpoint_input_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class CheckpointKey:
    step: str
    input_hash: str
    schema_version: int = 1


class CheckpointStore:
    def __init__(self, repository: Repository, run_id: UUID, lease_token: UUID):
        self.repository, self.run_id, self.lease_token = repository, run_id, lease_token

    def key(self, step: str, value: Any, *, schema_version: int = 1) -> CheckpointKey:
        return CheckpointKey(step, checkpoint_input_hash(value), schema_version)

    def start(self, key: CheckpointKey):
        return self.repository.start_checkpoint(
            self.run_id,
            step_key=key.step,
            input_hash=key.input_hash,
            schema_version=key.schema_version,
            lease_token=self.lease_token,
        )

    def complete(self, key: CheckpointKey, output: dict[str, object]) -> None:
        self.repository.complete_checkpoint(
            self.run_id,
            step_key=key.step,
            input_hash=key.input_hash,
            schema_version=key.schema_version,
            output=output,
            lease_token=self.lease_token,
        )
