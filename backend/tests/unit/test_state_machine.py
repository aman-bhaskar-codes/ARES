import pytest

from ares.domain.models import RunStatus
from ares.domain.state_machine import InvalidTransition, assert_transition


def test_happy_path_transition() -> None:
    assert_transition(RunStatus.QUEUED, RunStatus.PLANNING)


def test_terminal_state_cannot_restart() -> None:
    with pytest.raises(InvalidTransition):
        assert_transition(RunStatus.COMPLETED, RunStatus.PLANNING)


def test_resumed_planning_can_preserve_existing_evidence_as_partial() -> None:
    # Reclaimed runs reset to planning while retaining their previously stored evidence.
    # An expired deadline must allow that evidence to be finalized without another stage.
    assert_transition(RunStatus.PLANNING, RunStatus.PARTIAL)
