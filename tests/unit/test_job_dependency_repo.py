"""Unit tests for JobDependencyRepository."""

from datetime import UTC, datetime

import pytest

from contracts.errors import ContractError, ErrorCode
from database.models import ExperimentModel
from database.repositories.job_dependency_repo import JobDependencyRepository


def _add_exp(session, exp_id: str) -> None:
    session.add(
        ExperimentModel(
            exp_id=exp_id,
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="queued",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            target_atoms=1000,
            temperature_K=298.0,
            pressure_atm=1.0,
            seed=1,
            created_at=datetime.now(UTC),
        )
    )


def test_create_and_list_dependency(db_session) -> None:
    _add_exp(db_session, "exp_parent")
    _add_exp(db_session, "exp_child")
    db_session.commit()

    repo = JobDependencyRepository(db_session)
    edge_id = repo.create_dependency("exp_parent", "exp_child")
    assert edge_id == "exp_parent->exp_child"

    dependents = repo.list_dependents("exp_parent")
    assert len(dependents) == 1
    assert dependents[0]["child_exp_id"] == "exp_child"
    assert dependents[0]["status"] == "blocked"


def test_cycle_detection_raises_error(db_session) -> None:
    _add_exp(db_session, "exp_a")
    _add_exp(db_session, "exp_b")
    _add_exp(db_session, "exp_c")
    db_session.commit()

    repo = JobDependencyRepository(db_session)
    repo.create_dependency("exp_a", "exp_b")
    repo.create_dependency("exp_b", "exp_c")

    with pytest.raises(ContractError) as exc:
        repo.create_dependency("exp_c", "exp_a")

    assert exc.value.code == ErrorCode.DEPENDENCY_CYCLE
