"""Tests for experiment retry API behavior."""

from unittest.mock import MagicMock, Mock

import pytest

from contracts.errors import ContractError, ErrorCode
from database.models import ExperimentModel
from features.experiments.query import retry_experiment


@pytest.mark.asyncio
async def test_retry_experiment_resubmits_job(db_session, sample_experiments, monkeypatch):
    """Retry should resubmit and move existing experiment back to queued."""
    mock_manager = Mock()
    mock_manager.submit.return_value = "job_retry_001"
    mock_manager.get_task_id.return_value = "celery_retry_001"

    monkeypatch.setattr("api.deps.get_job_manager", lambda: mock_manager)
    monkeypatch.setattr("config.dashboard_settings.load_dashboard_settings", lambda: {})

    result = await retry_experiment("exp_test_001")

    assert result["exp_id"] == "exp_test_001"
    assert result["job_id"] == "job_retry_001"
    assert result["status"] == "queued"
    assert result["retry_count"] == 1
    assert mock_manager.submit.call_count == 1


@pytest.mark.asyncio
async def test_retry_experiment_rejects_active_status(db_session, sample_experiments, monkeypatch):
    """Retry should reject running experiments."""
    mock_manager = Mock()
    monkeypatch.setattr("api.deps.get_job_manager", lambda: mock_manager)
    monkeypatch.setattr("config.dashboard_settings.load_dashboard_settings", lambda: {})

    with pytest.raises(ContractError) as exc:
        await retry_experiment("exp_test_004")  # running fixture

    assert exc.value.code == ErrorCode.INVALID_REQUEST


# ---------------------------------------------------------------------------
# Single-Molecule Retry Tests
# ---------------------------------------------------------------------------


def _make_sm_experiment(exp_id: str, seed: int = 42, study_type: str = "single_molecule_vacuum"):
    """Create a mock single-molecule experiment."""
    exp = MagicMock()
    exp.exp_id = exp_id
    exp.status = "failed"
    exp.seed = seed
    exp.run_tier = "screening"
    exp.ff_type = "bulk_ff_gaff2"
    exp.temperature_K = 298.0
    exp.pressure_atm = 1.0
    exp.target_atoms = 50
    exp.study_type = study_type
    exp.retry_count = 0
    exp.prepared_artifact_json = None
    exp.metadata_json = None
    exp.stage_duration_overrides = None
    exp.additive_type = "test_mol"
    exp.additive_wt = 0.0
    exp.additive_mol_id = "test_mol"
    exp.comp_asphaltene_wt = 0.0
    exp.comp_resin_wt = 0.0
    exp.comp_aromatic_wt = 0.0
    exp.comp_saturate_wt = 0.0
    exp.celery_task_id = None
    exp.gpu_id_allocated = None
    return exp


class TestSingleMoleculeRetry:
    """Tests for single-molecule experiment retry behavior."""

    @pytest.mark.asyncio
    async def test_sm_retry_with_prepared_artifact(self, monkeypatch):
        """SM retry with prepared_artifact_json restores mol_count composition."""
        mock_manager = Mock()
        mock_manager.submit.return_value = "job_sm_001"
        mock_manager.get_task_id.return_value = "celery_sm_001"

        # Experiment with prepared_artifact_json containing original requests
        exp = _make_sm_experiment("SM_test_001", seed=10)
        exp.metadata_json = {"e_intra_method": "single_molecule_vacuum_adaptive_cutoff"}
        exp.prepared_artifact_json = {
            "build_request": {
                "composition": {"U-AS-Thio-0298": 1.0},
                "composition_mode": "mol_count",
                "target_atoms": 50,
                "initial_density": 0.01,
                "seed": 10,
            },
            "protocol_request": {
                "tier": "screening",
                "ff_type": "bulk_ff_gaff2",
                "temperature_K": 298.0,
                "pressure_atm": 1.0,
                "study_type": "single_molecule_vacuum",
                "skip_stage_keys": ["npt_production"],
            },
        }

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = exp
        mock_repo.increment_retry.return_value = 1

        # Patch dependencies
        monkeypatch.setattr("api.deps.get_job_manager", lambda: mock_manager)
        monkeypatch.setattr("config.dashboard_settings.load_dashboard_settings", lambda: {})

        def mock_run_in_session_commit(fn):
            session = MagicMock()
            with monkeypatch.context() as m:
                m.setattr(
                    "database.repositories.experiment_repo.ExperimentRepository",
                    lambda s: mock_repo,
                )
                return fn(session)

        monkeypatch.setattr(
            "features.experiments.experiment_lifecycle.run_in_session_commit",
            mock_run_in_session_commit,
        )

        result = await retry_experiment("SM_test_001")

        assert result["exp_id"] == "SM_test_001"
        assert result["status"] == "queued"

        # Verify submit was called with mol_count composition
        call_kwargs = mock_manager.submit.call_args.kwargs
        assert call_kwargs["build_request"].composition_mode == "mol_count"
        assert call_kwargs["build_request"].composition == {"U-AS-Thio-0298": 1.0}
        assert call_kwargs["build_request"].seed == 11  # seed+1
        assert call_kwargs["protocol_request"].study_type == "single_molecule_vacuum"
        assert (
            call_kwargs["protocol_request"].e_intra_method
            == "single_molecule_vacuum_adaptive_cutoff"
        )
        assert call_kwargs["protocol_request"].skip_stage_keys == ["npt_production"]

    @pytest.mark.asyncio
    async def test_sm_retry_with_deferred_submission(self, monkeypatch):
        """SM retry with deferred_submission in metadata_json."""
        mock_manager = Mock()
        mock_manager.submit.return_value = "job_sm_002"
        mock_manager.get_task_id.return_value = "celery_sm_002"

        exp = _make_sm_experiment("SM_test_002", seed=20)
        exp.metadata_json = {
            "e_intra_method": "single_molecule_vacuum_adaptive_cutoff",
            "deferred_submission": {
                "build_request": {
                    "composition": {"U-RE-Qui-0298": 1.0},
                    "composition_mode": "mol_count",
                    "target_atoms": 75,
                    "initial_density": 0.01,
                    "seed": 20,
                },
                "protocol_request": {
                    "tier": "screening",
                    "ff_type": "bulk_ff_gaff2",
                    "temperature_K": 323.0,
                    "pressure_atm": 1.0,
                    "study_type": "single_molecule_vacuum",
                    "skip_stage_keys": ["npt_production"],
                },
            },
        }

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = exp
        mock_repo.increment_retry.return_value = 1

        monkeypatch.setattr("api.deps.get_job_manager", lambda: mock_manager)
        monkeypatch.setattr("config.dashboard_settings.load_dashboard_settings", lambda: {})

        def mock_run_in_session_commit(fn):
            session = MagicMock()
            with monkeypatch.context() as m:
                m.setattr(
                    "database.repositories.experiment_repo.ExperimentRepository",
                    lambda s: mock_repo,
                )
                return fn(session)

        monkeypatch.setattr(
            "features.experiments.experiment_lifecycle.run_in_session_commit",
            mock_run_in_session_commit,
        )

        result = await retry_experiment("SM_test_002")

        assert result["status"] == "queued"
        call_kwargs = mock_manager.submit.call_args.kwargs
        assert call_kwargs["build_request"].composition == {"U-RE-Qui-0298": 1.0}
        assert call_kwargs["build_request"].seed == 21
        assert (
            call_kwargs["protocol_request"].e_intra_method
            == "single_molecule_vacuum_adaptive_cutoff"
        )

    @pytest.mark.asyncio
    async def test_sm_retry_with_db_molecules(self, monkeypatch):
        """SM retry restored from experiment_molecules DB when no artifact."""
        mock_manager = Mock()
        mock_manager.submit.return_value = "job_sm_003"
        mock_manager.get_task_id.return_value = "celery_sm_003"

        exp = _make_sm_experiment("SM_test_003", seed=30)
        # No prepared_artifact_json, no deferred_submission

        # Mock experiment_molecules DB result
        mock_exp_mol = MagicMock()
        mock_exp_mol.count = 1
        mock_mol = MagicMock()
        mock_mol.mol_id = "U-AR-Ben-0298"

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = exp
        mock_repo.get_experiment_molecules.return_value = [(mock_exp_mol, mock_mol)]
        mock_repo.increment_retry.return_value = 1

        monkeypatch.setattr("api.deps.get_job_manager", lambda: mock_manager)
        monkeypatch.setattr("config.dashboard_settings.load_dashboard_settings", lambda: {})

        def mock_run_in_session_commit(fn):
            session = MagicMock()
            with monkeypatch.context() as m:
                m.setattr(
                    "database.repositories.experiment_repo.ExperimentRepository",
                    lambda s: mock_repo,
                )
                return fn(session)

        monkeypatch.setattr(
            "features.experiments.experiment_lifecycle.run_in_session_commit",
            mock_run_in_session_commit,
        )

        result = await retry_experiment("SM_test_003")

        assert result["status"] == "queued"
        call_kwargs = mock_manager.submit.call_args.kwargs
        assert call_kwargs["build_request"].composition_mode == "mol_count"
        assert call_kwargs["build_request"].composition == {"U-AR-Ben-0298": 1}
        assert call_kwargs["build_request"].seed == 31
        assert call_kwargs["protocol_request"].study_type == "single_molecule_vacuum"
        assert call_kwargs["protocol_request"].e_intra_method == "single_molecule_vacuum"

    @pytest.mark.asyncio
    async def test_sm_retry_with_db_molecules_ignores_current_settings_default(self, monkeypatch):
        """Missing SM provenance falls back to explicit baseline, not current settings."""
        mock_manager = Mock()
        mock_manager.submit.return_value = "job_sm_003a"
        mock_manager.get_task_id.return_value = "celery_sm_003a"

        exp = _make_sm_experiment("SM_test_003a", seed=31)

        mock_exp_mol = MagicMock()
        mock_exp_mol.count = 1
        mock_mol = MagicMock()
        mock_mol.mol_id = "U-AR-Ben-0298"

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = exp
        mock_repo.get_experiment_molecules.return_value = [(mock_exp_mol, mock_mol)]
        mock_repo.increment_retry.return_value = 1

        monkeypatch.setattr("api.deps.get_job_manager", lambda: mock_manager)
        monkeypatch.setattr(
            "config.dashboard_settings.load_dashboard_settings",
            lambda: {"default_e_intra_method": "single_molecule_vacuum_adaptive_cutoff"},
        )

        def mock_run_in_session_commit(fn):
            session = MagicMock()
            with monkeypatch.context() as m:
                m.setattr(
                    "database.repositories.experiment_repo.ExperimentRepository",
                    lambda s: mock_repo,
                )
                return fn(session)

        monkeypatch.setattr(
            "features.experiments.experiment_lifecycle.run_in_session_commit",
            mock_run_in_session_commit,
        )

        result = await retry_experiment("SM_test_003a")

        assert result["status"] == "queued"
        call_kwargs = mock_manager.submit.call_args.kwargs
        assert call_kwargs["protocol_request"].e_intra_method == "single_molecule_vacuum"

    @pytest.mark.asyncio
    async def test_sm_retry_no_restoration_source_raises(self, monkeypatch):
        """SM retry without any restoration source raises ContractError."""
        mock_manager = Mock()

        exp = _make_sm_experiment("SM_test_004", seed=40)
        # No prepared_artifact_json, no deferred_submission, no experiment_molecules

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = exp
        mock_repo.get_experiment_molecules.return_value = []  # Empty!

        monkeypatch.setattr("api.deps.get_job_manager", lambda: mock_manager)
        monkeypatch.setattr("config.dashboard_settings.load_dashboard_settings", lambda: {})

        def mock_run_in_session_commit(fn):
            session = MagicMock()
            with monkeypatch.context() as m:
                m.setattr(
                    "database.repositories.experiment_repo.ExperimentRepository",
                    lambda s: mock_repo,
                )
                return fn(session)

        monkeypatch.setattr(
            "features.experiments.experiment_lifecycle.run_in_session_commit",
            mock_run_in_session_commit,
        )

        with pytest.raises(ContractError) as exc:
            await retry_experiment("SM_test_004")

        assert exc.value.code == ErrorCode.INVALID_REQUEST
        assert "resubmit required" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_sm_retry_corrupted_stage_overrides_raises(self, monkeypatch):
        """SM retry with corrupted stage_duration_overrides raises ContractError."""
        mock_manager = Mock()
        mock_manager.submit.return_value = "job_sm_005"
        mock_manager.get_task_id.return_value = "celery_sm_005"

        exp = _make_sm_experiment("SM_test_005", seed=50)
        exp.prepared_artifact_json = {
            "build_request": {
                "composition": {"U-SA-Hex-0298": 1.0},
                "composition_mode": "mol_count",
                "target_atoms": 50,
                "initial_density": 0.01,
                "seed": 50,
            },
            "protocol_request": {
                "tier": "screening",
                "ff_type": "bulk_ff_gaff2",
                "temperature_K": 298.0,
                "pressure_atm": 1.0,
                "study_type": "single_molecule_vacuum",
                "skip_stage_keys": ["npt_production"],
            },
            # NO stage_duration_overrides in artifact
        }
        # But corrupted overrides in exp
        exp.stage_duration_overrides = [{"invalid": "data"}]

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = exp
        mock_repo.increment_retry.return_value = 1

        monkeypatch.setattr("api.deps.get_job_manager", lambda: mock_manager)
        monkeypatch.setattr("config.dashboard_settings.load_dashboard_settings", lambda: {})

        def mock_run_in_session_commit(fn):
            session = MagicMock()
            with monkeypatch.context() as m:
                m.setattr(
                    "database.repositories.experiment_repo.ExperimentRepository",
                    lambda s: mock_repo,
                )
                return fn(session)

        monkeypatch.setattr(
            "features.experiments.experiment_lifecycle.run_in_session_commit",
            mock_run_in_session_commit,
        )

        with pytest.raises(ContractError) as exc:
            await retry_experiment("SM_test_005")

        assert exc.value.code == ErrorCode.INVALID_REQUEST
        assert "stage_duration_overrides" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_sm_retry_submit_valueerror_surfaces(self, monkeypatch):
        """job_manager.submit() ValueError is surfaced as ContractError."""
        mock_manager = Mock()
        mock_manager.submit.side_effect = ValueError("GPU unavailable")

        exp = _make_sm_experiment("SM_test_006", seed=60)
        exp.prepared_artifact_json = {
            "build_request": {
                "composition": {"U-AS-Thio-0298": 1.0},
                "composition_mode": "mol_count",
                "target_atoms": 50,
                "initial_density": 0.01,
                "seed": 60,
            },
            "protocol_request": {
                "tier": "screening",
                "ff_type": "bulk_ff_gaff2",
                "temperature_K": 298.0,
                "pressure_atm": 1.0,
                "study_type": "single_molecule_vacuum",
                "skip_stage_keys": ["npt_production"],
            },
        }

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = exp

        monkeypatch.setattr("api.deps.get_job_manager", lambda: mock_manager)
        monkeypatch.setattr("config.dashboard_settings.load_dashboard_settings", lambda: {})

        def mock_run_in_session_commit(fn):
            session = MagicMock()
            with monkeypatch.context() as m:
                m.setattr(
                    "database.repositories.experiment_repo.ExperimentRepository",
                    lambda s: mock_repo,
                )
                return fn(session)

        monkeypatch.setattr(
            "features.experiments.experiment_lifecycle.run_in_session_commit",
            mock_run_in_session_commit,
        )

        with pytest.raises(ContractError) as exc:
            await retry_experiment("SM_test_006")

        assert exc.value.code == ErrorCode.INVALID_REQUEST
        assert "GPU unavailable" in str(exc.value.message)


class TestBulkRetryUnchanged:
    """Tests ensuring bulk/layer experiments still use SARA fallback."""

    @pytest.mark.asyncio
    async def test_bulk_retry_uses_sara_fallback(self, db_session, sample_experiments, monkeypatch):
        """Bulk experiment retry uses SARA composition (existing behavior)."""
        mock_manager = Mock()
        mock_manager.submit.return_value = "job_bulk_001"
        mock_manager.get_task_id.return_value = "celery_bulk_001"

        monkeypatch.setattr("api.deps.get_job_manager", lambda: mock_manager)
        monkeypatch.setattr("config.dashboard_settings.load_dashboard_settings", lambda: {})

        result = await retry_experiment("exp_test_001")

        assert result["status"] == "queued"
        call_kwargs = mock_manager.submit.call_args.kwargs
        # Bulk experiment: SARA-based composition
        build_req = call_kwargs["build_request"]
        assert build_req.composition.get("asphaltene") == 20.0
        assert build_req.composition.get("resin") == 30.0

    @pytest.mark.asyncio
    async def test_bulk_retry_preserves_e_intra_method_from_metadata(
        self, db_session, sample_experiments, monkeypatch
    ):
        """Bulk/layer retry must preserve the original method instead of drifting to settings."""
        mock_manager = Mock()
        mock_manager.submit.return_value = "job_bulk_method_001"
        mock_manager.get_task_id.return_value = "celery_bulk_method_001"

        exp = db_session.query(ExperimentModel).filter_by(exp_id="exp_test_001").first()
        exp.metadata_json = {"e_intra_method": "single_molecule_vacuum_adaptive_cutoff"}
        db_session.commit()

        monkeypatch.setattr("api.deps.get_job_manager", lambda: mock_manager)
        monkeypatch.setattr(
            "config.dashboard_settings.load_dashboard_settings",
            lambda: {"default_e_intra_method": "single_molecule_vacuum"},
        )

        result = await retry_experiment("exp_test_001")

        assert result["status"] == "queued"
        call_kwargs = mock_manager.submit.call_args.kwargs
        assert (
            call_kwargs["protocol_request"].e_intra_method
            == "single_molecule_vacuum_adaptive_cutoff"
        )
