"""Unit tests for BatchJobBinderCellRunner and temperature scan presets."""

from unittest.mock import MagicMock, patch

import pytest

from common.seed import generate_seed
from contracts.policies.temperature import DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K
from orchestrator.batch_job_binder_cell import BatchJobBinderCellRunner, BatchJobBinderCellSpec
from orchestrator.temperature_scan import (
    STANDARD_TEMPERATURES,
    aging_comparison_scan,
    full_screening_scan,
    quick_validation_scan,
)

_N_STANDARD_TEMPS = len(DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K)

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_experiment_repo():
    """Create a mock ExperimentRepository."""
    repo = MagicMock()
    repo.get_by_id.return_value = None  # no duplicates by default
    return repo


@pytest.fixture
def mock_molecule_db():
    """Create a mock MoleculeDB."""
    db = MagicMock()
    db.get_temperature_code.return_value = "0293"
    db.get_binder_composition_with_aging.return_value = {
        "U-SA-Squalane-0293": 4,
        "U-SA-Hopane-0293": 4,
        "U-AR-PHPN-0293": 11,
        "U-AR-DOCHN-0293": 13,
    }
    db.get_aging_config.return_value = {"binders": {"AAA1": {}}}
    return db


@pytest.fixture
def mock_job_manager():
    """Create a mock CeleryJobManager."""
    jm = MagicMock()
    jm.submit.return_value = "job_001"
    jm.get_task_id.return_value = "task_001"
    return jm


@pytest.fixture(autouse=True)
def _isolated_db():
    """Ensure SubmissionFacade DB writes do not leak across tests."""
    from database.connection import close_db, init_memory_db

    session = init_memory_db()
    session.close()
    yield
    close_db()


@pytest.fixture
def batch_job_runner(mock_experiment_repo, mock_molecule_db, mock_job_manager):
    """Create a BatchJobBinderCellRunner with mocked deps."""
    runner = BatchJobBinderCellRunner(
        experiment_repo=mock_experiment_repo,
        molecule_db=mock_molecule_db,
        job_manager=mock_job_manager,
    )
    runner._config = {"binders": {"AAA1": {}}}
    return runner


# ── BatchJobBinderCellSpec tests ──────────────────────────────────────────────


class TestBatchJobSpec:
    """Tests for BatchJobBinderCellSpec dataclass defaults."""

    def test_default_values(self):
        """BatchJobBinderCellSpec has sensible defaults."""
        spec = BatchJobBinderCellSpec(binder_types=["AAA1"])
        expected_seed = generate_seed()
        assert spec.structure_sizes == ["X1"]
        assert len(spec.temperatures_k) == _N_STANDARD_TEMPS
        assert spec.tier == "screening"
        assert spec.seed == expected_seed
        assert spec.seeds == []
        assert 293.0 in spec.temperature_priority
        assert 313.0 in spec.temperature_priority


# ── Job generation tests ────────────────────────────────────────────


class TestJobGeneration:
    """Tests for BatchJobBinderCellRunner._generate_jobs()."""

    def test_generates_correct_count(self, batch_job_runner):
        """3 binders x N temps x 1 aging = 3*N jobs."""
        spec = BatchJobBinderCellSpec(
            binder_types=["AAA1", "AAK1", "AAM1"],
            temperatures_k=STANDARD_TEMPERATURES,
            aging_states=["non_aging"],
        )
        jobs = batch_job_runner._generate_jobs(spec)
        assert len(jobs) == 3 * _N_STANDARD_TEMPS

    def test_single_binder_single_temp(self, batch_job_runner):
        """1 binder x 1 temp = 1 job."""
        spec = BatchJobBinderCellSpec(
            binder_types=["AAA1"],
            temperatures_k=[298.0],
            aging_states=["non_aging"],
        )
        jobs = batch_job_runner._generate_jobs(spec)
        assert len(jobs) == 1
        assert jobs[0].binder_type == "AAA1"
        assert jobs[0].temperature_k == 298.0

    def test_priority_temperatures_sorted_first(self, batch_job_runner):
        """Priority temperatures should appear before non-priority."""
        spec = BatchJobBinderCellSpec(
            binder_types=["AAA1"],
            temperatures_k=[373.0, 293.0, 273.0, 313.0, 333.0],
            temperature_priority=[293.0, 313.0],
        )
        jobs = batch_job_runner._generate_jobs(spec)
        # First two should be priority temps (293, 313)
        assert jobs[0].temperature_k in {293.0, 313.0}
        assert jobs[1].temperature_k in {293.0, 313.0}

    def test_aging_combinations(self, batch_job_runner):
        """1 binder x 2 temps x 3 aging = 6 jobs."""
        spec = BatchJobBinderCellSpec(
            binder_types=["AAA1"],
            temperatures_k=[293.0, 313.0],
            aging_states=["non_aging", "short_aging", "long_aging"],
        )
        jobs = batch_job_runner._generate_jobs(spec)
        assert len(jobs) == 6

    def test_each_job_has_unique_exp_id(self, batch_job_runner):
        """All generated jobs have unique experiment IDs."""
        spec = BatchJobBinderCellSpec(
            binder_types=["AAA1", "AAK1"],
            temperatures_k=[293.0, 313.0],
        )
        jobs = batch_job_runner._generate_jobs(spec)
        exp_ids = [j.exp_id for j in jobs]
        assert len(exp_ids) == len(set(exp_ids))

    def test_single_item_seeds_list_is_respected(self, batch_job_runner):
        """A single provided seed in seeds should be used as-is."""
        spec = BatchJobBinderCellSpec(
            binder_types=["AAA1"],
            temperatures_k=[293.0],
            seed=1,
            seeds=[42],
        )
        jobs = batch_job_runner._generate_jobs(spec)
        assert len(jobs) == 1
        assert jobs[0].seed == 42

    def test_empty_seeds_list_falls_back_to_seed(self, batch_job_runner):
        """If seeds is empty, fallback to legacy single seed."""
        spec = BatchJobBinderCellSpec(
            binder_types=["AAA1"],
            temperatures_k=[293.0],
            seed=7,
            seeds=[],
        )
        jobs = batch_job_runner._generate_jobs(spec)
        assert len(jobs) == 1
        assert jobs[0].seed == 7


# ── Validate tests ──────────────────────────────────────────────────


class TestValidate:
    """Tests for BatchJobBinderCellRunner.validate()."""

    def test_validate_all_new(self, batch_job_runner, mock_experiment_repo):
        """All jobs are new when no duplicates exist."""
        mock_experiment_repo.get_by_id.return_value = None
        spec = BatchJobBinderCellSpec(
            binder_types=["AAA1"],
            temperatures_k=[293.0, 313.0],
        )

        result = batch_job_runner.validate(spec)

        assert result.total == 2
        assert result.new == 2
        assert result.duplicates == 0
        assert result.submitted == 0

    def test_validate_detects_duplicates(self, batch_job_runner, mock_experiment_repo):
        """Existing experiments are marked as duplicates."""
        # First call returns existing, rest return None
        existing = MagicMock()
        existing.status = "completed"
        mock_experiment_repo.get_by_id.side_effect = [existing, None]

        spec = BatchJobBinderCellSpec(
            binder_types=["AAA1"],
            temperatures_k=[293.0, 313.0],
        )

        result = batch_job_runner.validate(spec)

        assert result.total == 2
        assert result.duplicates == 1
        assert result.new == 1

    def test_validate_returns_batch_job_id(self, batch_job_runner):
        """Result includes a batch job ID."""
        spec = BatchJobBinderCellSpec(binder_types=["AAA1"], temperatures_k=[293.0])
        result = batch_job_runner.validate(spec)
        assert result.batch_job_id.startswith("batch_job_binder_cell_")


# ── Submit tests ────────────────────────────────────────────────────


class TestSubmit:
    """Tests for BatchJobBinderCellRunner.submit()."""

    def test_submit_new_jobs(self, batch_job_runner, mock_experiment_repo, mock_job_manager):
        """New jobs are submitted via CeleryJobManager.submit()."""
        mock_experiment_repo.get_by_id.return_value = None

        spec = BatchJobBinderCellSpec(
            binder_types=["AAA1"],
            temperatures_k=[293.0],
        )

        result = batch_job_runner.submit(spec)

        assert result.submitted == 1
        assert result.duplicates == 0
        mock_job_manager.submit.assert_called_once()
        call_kwargs = mock_job_manager.submit.call_args[1]
        assert "build_request" in call_kwargs
        assert "protocol_request" in call_kwargs
        assert "material_id" in call_kwargs
        assert "exp_id" in call_kwargs

    def test_submit_skips_duplicates(
        self, batch_job_runner, mock_experiment_repo, mock_job_manager
    ):
        """Duplicate jobs are not submitted."""
        existing = MagicMock()
        existing.status = "completed"
        mock_experiment_repo.get_by_id.return_value = existing

        spec = BatchJobBinderCellSpec(
            binder_types=["AAA1"],
            temperatures_k=[293.0],
        )

        result = batch_job_runner.submit(spec)

        assert result.submitted == 0
        assert result.duplicates == 1
        mock_job_manager.submit.assert_not_called()

    def test_submit_handles_errors(
        self, batch_job_runner, mock_experiment_repo, mock_molecule_db, mock_job_manager
    ):
        """Errors during submission are captured per-job."""
        mock_experiment_repo.get_by_id.return_value = None
        mock_molecule_db.get_binder_composition_with_aging.side_effect = ValueError("bad binder")

        spec = BatchJobBinderCellSpec(
            binder_types=["AAA1"],
            temperatures_k=[293.0],
        )

        result = batch_job_runner.submit(spec)

        assert result.errors == 1
        assert result.submitted == 0
        assert result.jobs[0].status == "error"
        assert "bad binder" in result.jobs[0].error

    def test_submit_without_job_manager_raises(self, mock_experiment_repo, mock_molecule_db):
        """submit() raises RuntimeError if job_manager is not provided."""
        runner = BatchJobBinderCellRunner(
            experiment_repo=mock_experiment_repo,
            molecule_db=mock_molecule_db,
        )
        runner._config = {"binders": {"AAA1": {}}}

        spec = BatchJobBinderCellSpec(binder_types=["AAA1"], temperatures_k=[293.0])

        with pytest.raises(RuntimeError, match="requires a job_manager"):
            runner.submit(spec)

    def test_submit_persists_e_intra_method_metadata(self, batch_job_runner):
        """New binder-cell jobs must persist the resolved bulk CED method tag."""
        spec = BatchJobBinderCellSpec(
            binder_types=["AAA1"],
            temperatures_k=[293.0],
            e_intra_method="single_molecule_vacuum_adaptive_cutoff",
            e_intra_method_source="request",
        )

        with patch(
            "orchestrator.batch_job_binder_cell.SubmissionFacade.submit_experiment"
        ) as submit:
            submit.return_value = ("job_001", "task_001")
            result = batch_job_runner.submit(spec)

        assert result.submitted == 1
        kwargs = submit.call_args.kwargs
        assert kwargs["protocol_request"].e_intra_method == "single_molecule_vacuum_adaptive_cutoff"
        assert kwargs["metadata_json"]["e_intra_method"] == "single_molecule_vacuum_adaptive_cutoff"
        assert kwargs["metadata_json"]["ced_provenance"]["e_intra_method_source"] == "request"


# ── Temperature scan preset tests ───────────────────────────────────


class TestTemperatureScanPresets:
    """Tests for temperature scan factory functions."""

    def test_full_screening_scan(self):
        """full_screening_scan produces 3 x N_temps x 1 jobs."""
        spec = full_screening_scan()
        assert spec.binder_types == ["AAA1", "AAK1", "AAM1"]
        assert len(spec.temperatures_k) == _N_STANDARD_TEMPS
        assert spec.aging_states == ["non_aging"]
        assert spec.tier == "screening"
        total = (
            len(spec.binder_types)
            * len(spec.structure_sizes)
            * len(spec.temperatures_k)
            * len(spec.aging_states)
        )
        assert total == 3 * _N_STANDARD_TEMPS

    def test_aging_comparison_scan(self):
        """aging_comparison_scan produces 1 x N_temps x 3 jobs."""
        spec = aging_comparison_scan(binder_type="AAK1")
        assert spec.binder_types == ["AAK1"]
        assert len(spec.aging_states) == 3
        total = (
            len(spec.binder_types)
            * len(spec.structure_sizes)
            * len(spec.temperatures_k)
            * len(spec.aging_states)
        )
        assert total == 3 * _N_STANDARD_TEMPS

    def test_quick_validation_scan(self):
        """quick_validation_scan produces 3x2 = 6 jobs."""
        spec = quick_validation_scan()
        assert len(spec.temperatures_k) == 2
        total = (
            len(spec.binder_types)
            * len(spec.structure_sizes)
            * len(spec.temperatures_k)
            * len(spec.aging_states)
        )
        assert total == 6

    def test_custom_binder_types(self):
        """Presets accept custom binder types."""
        spec = full_screening_scan(binder_types=["AAA1"])
        assert spec.binder_types == ["AAA1"]

    def test_custom_seed(self):
        """Presets accept custom seed."""
        spec = full_screening_scan(seed=42)
        assert spec.seed == 42
