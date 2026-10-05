import pytest

from ares.domain.models import RunStatus
from ares.domain.state_machine import InvalidTransition, assert_transition


def test_happy_path_transition() -> None:
    assert_transition(RunStatus.QUEUED, RunStatus.PLANNING)


def test_terminal_state_cannot_restart() -> None:
    with pytest.raises(InvalidTransition):
        assert_transition(RunStatus.COMPLETED, RunStatus.PLANNING)
