from __future__ import annotations

from ares.domain.models import RunStatus


class InvalidTransition(ValueError):
    pass


_ALLOWED: dict[RunStatus, set[RunStatus]] = {
    RunStatus.QUEUED: {RunStatus.PLANNING, RunStatus.CANCELLED, RunStatus.FAILED},
    RunStatus.PLANNING: {RunStatus.DISCOVERING, RunStatus.PARTIAL, RunStatus.CANCELLED, RunStatus.FAILED},
    RunStatus.DISCOVERING: {
        RunStatus.READING,
        RunStatus.CHECKING,
        RunStatus.PARTIAL,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    },
    RunStatus.READING: {
        RunStatus.EXTRACTING,
        RunStatus.PARTIAL,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    },
    RunStatus.EXTRACTING: {
        RunStatus.CHECKING,
        RunStatus.PARTIAL,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    },
    RunStatus.CHECKING: {
        RunStatus.DISCOVERING,
        RunStatus.SYNTHESIZING,
        RunStatus.PARTIAL,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    },
    RunStatus.SYNTHESIZING: {
        RunStatus.COMPLETED,
        RunStatus.PARTIAL,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    },
    RunStatus.COMPLETED: set(),
    RunStatus.PARTIAL: set(),
    RunStatus.CANCELLED: set(),
    RunStatus.FAILED: set(),
}


def assert_transition(current: RunStatus, target: RunStatus) -> None:
    if target not in _ALLOWED[current]:
        raise InvalidTransition(f"invalid run transition: {current.value} -> {target.value}")
