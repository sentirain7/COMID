"""Regression tests for single-molecule E_intra storage semantics."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from contracts.schema_enums import FFType, StudyType
from contracts.schemas import MetricResult
from orchestrator.pipeline import Pipeline


def _protocol() -> SimpleNamespace:
    return SimpleNamespace(
        study_type=StudyType.SINGLE_MOLECULE_VACUUM,
        ff_type=FFType.BULK_FF_GAFF2,
        temperature_K=213.0,
    )


def test_single_molecule_e_intra_missing_potential_energy_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="Missing potential_energy"):
        Pipeline._store_e_intra_from_metrics(
            metrics=[],
            lammps_result=SimpleNamespace(force_field="GAFF2", ff_version="2.11"),
            build_request=SimpleNamespace(composition_mode="mol_count", composition={"mol_001": 1}),
            protocol_request=_protocol(),
            exp_id="exp_missing_pe",
        )


def test_single_molecule_e_intra_missing_mol_id_fails_closed() -> None:
    metrics = [
        MetricResult(
            metric_name="potential_energy",
            value=-100.0,
            unit="kcal/mol",
            namespace="bulk_ff",
        )
    ]

    with pytest.raises(RuntimeError, match="Cannot determine mol_id"):
        Pipeline._store_e_intra_from_metrics(
            metrics=metrics,
            lammps_result=SimpleNamespace(force_field="GAFF2", ff_version="2.11"),
            build_request=SimpleNamespace(composition_mode="mol_count", composition={}),
            protocol_request=_protocol(),
            exp_id="exp_missing_mol",
        )


def test_single_molecule_e_intra_commits_via_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics = [
        MetricResult(
            metric_name="potential_energy",
            value=-100.0,
            unit="kcal/mol",
            namespace="bulk_ff",
        )
    ]
    captured: dict[str, object] = {}

    class DummySession:
        def commit(self) -> None:
            captured["committed"] = True

    @contextmanager
    def fake_session_scope():
        yield DummySession()

    class FakeRepo:
        def __init__(self, session):
            captured["session"] = session

        def set(self, key, value) -> None:
            captured["key"] = key
            captured["value"] = value

    import database.connection
    import database.repositories.e_intra_repo

    monkeypatch.setattr(database.connection, "session_scope", fake_session_scope)
    monkeypatch.setattr(database.repositories.e_intra_repo, "EIntraRepository", FakeRepo)

    Pipeline._store_e_intra_from_metrics(
        metrics=metrics,
        lammps_result=SimpleNamespace(force_field="GAFF2", ff_version="2.11"),
        build_request=SimpleNamespace(composition_mode="mol_count", composition={"mol_001": 1}),
        protocol_request=_protocol(),
        exp_id="exp_repo_commit",
    )

    assert captured["committed"] is True
    assert captured["key"].mol_id == "mol_001"
    assert captured["value"].e_intra == pytest.approx(-100.0)
