import pytest

from contracts.errors import ContractError, ErrorCode
from contracts.policies.state_machine import ensure_valid_experiment_transition


def test_valid_experiment_transition_chain() -> None:
    ensure_valid_experiment_transition("pending", "queued")
    ensure_valid_experiment_transition("queued", "building")
    ensure_valid_experiment_transition("building", "ready")
    ensure_valid_experiment_transition("ready", "running")
    ensure_valid_experiment_transition("running", "completed")


def test_invalid_terminal_to_running_transition_blocked() -> None:
    with pytest.raises(ContractError) as exc:
        ensure_valid_experiment_transition("completed", "running")

    assert exc.value.code == ErrorCode.INVALID_STATE_TRANSITION


def test_building_must_pass_through_ready() -> None:
    """building → running is blocked; must go building → ready → running."""
    with pytest.raises(ContractError) as exc:
        ensure_valid_experiment_transition("building", "running")
    assert exc.value.code == ErrorCode.INVALID_STATE_TRANSITION

    # Correct path
    ensure_valid_experiment_transition("building", "ready")
    ensure_valid_experiment_transition("ready", "running")
