"""Tests for Phase 5.1 additive batch-job implementation.

These tests use real production classes from orchestrator.batch_job_binder_cell.
External dependencies (DB/job manager/molecule DB) are mocked only at boundaries.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from api.schemas import BatchJobBinderCellRequest
from orchestrator.batch_job_binder_cell import (
    AdditiveBatchJobBinderCellJob,
    AdditiveBatchJobBinderCellRunner,
    BatchJobBinderCellRunner,
    BatchJobBinderCellSpec,
)


@pytest.fixture
def mock_experiment_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_by_id.return_value = None
    return repo


@pytest.fixture
def mock_job_manager() -> MagicMock:
    jm = MagicMock()
    jm.submit.return_value = "job_001"
    jm.get_task_id.return_value = "task_001"
    return jm


@pytest.fixture
def mock_molecule_db() -> MagicMock:
    db = MagicMock()
    db.get_temperature_code.return_value = "0293"
    db.get_binder_composition_with_aging.return_value = {
        "U-SA-Squalane-0293": 40,
        "U-SA-Hopane-0293": 40,
    }
    db.get_aging_config.return_value = {
        "additives": {
            "SiO2": {
                "counts": {"X1": 2, "X2": 4, "X3": 6},
            }
        }
    }
    # Current MoleculeDB path may not include additive molecules for packing.
    db.has.return_value = False
    return db


@pytest.fixture
def additive_runner(
    mock_experiment_repo, mock_molecule_db, mock_job_manager
) -> AdditiveBatchJobBinderCellRunner:
    return AdditiveBatchJobBinderCellRunner(
        experiment_repo=mock_experiment_repo,
        molecule_db=mock_molecule_db,
        job_manager=mock_job_manager,
    )


@pytest.fixture(autouse=True)
def _isolated_db():
    """Ensure SubmissionFacade DB writes do not leak across tests."""
    from database.connection import close_db, init_memory_db

    session = init_memory_db()
    session.close()
    yield
    close_db()


def test_batch_job_spec_backward_compat() -> None:
    spec = BatchJobBinderCellSpec(binder_types=["AAA1"], temperatures_k=[293.0])
    assert spec.additive_types == []
    assert spec.additive_concentrations == []


def test_doe_matrix_full_factorial(additive_runner: AdditiveBatchJobBinderCellRunner) -> None:
    """DOE mode: full factorial when len(types) != len(concentrations)."""
    spec = BatchJobBinderCellSpec(
        binder_types=["AAA1"],
        additive_types=["none", "SiO2", "Lignin"],
        # 3 concentrations != 2 real_types → triggers DOE (full factorial) mode
        additive_concentrations=[2.0, 3.0, 5.0],
    )
    combos = additive_runner._generate_additive_combos(spec)
    # control + (2 types x 3 concentrations) = 1 + 6 = 7
    assert len(combos) == 7
    assert (None, 0.0) in combos
    assert ("SiO2", 2.0) in combos
    assert ("SiO2", 3.0) in combos
    assert ("SiO2", 5.0) in combos
    assert ("Lignin", 2.0) in combos
    assert ("Lignin", 3.0) in combos
    assert ("Lignin", 5.0) in combos


def test_binder_cell_1to1_mapping(additive_runner: AdditiveBatchJobBinderCellRunner) -> None:
    """Binder cell mode: 1:1 mapping when len(types) == len(concentrations)."""
    spec = BatchJobBinderCellSpec(
        binder_types=["AAA1"],
        additive_types=["none", "SiO2", "Lignin"],
        # 2 concentrations == 2 real_types → triggers 1:1 mapping mode
        additive_concentrations=[3.0, 5.0],
    )
    combos = additive_runner._generate_additive_combos(spec)
    # control + (SiO2→3.0, Lignin→5.0) = 1 + 2 = 3
    assert len(combos) == 3
    assert (None, 0.0) in combos
    assert ("SiO2", 3.0) in combos
    assert ("Lignin", 5.0) in combos
    # Cross products should NOT exist in binder cell mode
    assert ("SiO2", 5.0) not in combos
    assert ("Lignin", 3.0) not in combos


def test_control_group_auto_included(additive_runner: AdditiveBatchJobBinderCellRunner) -> None:
    spec = BatchJobBinderCellSpec(
        binder_types=["AAA1"],
        additive_types=["none", "SiO2"],
        additive_concentrations=[5.0],
    )
    combos = additive_runner._generate_additive_combos(spec)
    assert combos[0] == (None, 0.0)


def test_no_control_group_without_none(additive_runner: AdditiveBatchJobBinderCellRunner) -> None:
    """When 'none' is not in additive_types, no control group is generated."""
    spec = BatchJobBinderCellSpec(
        binder_types=["AAA1"],
        additive_types=["SiO2"],
        additive_concentrations=[5.0],
    )
    combos = additive_runner._generate_additive_combos(spec)
    assert (None, 0.0) not in combos
    assert len(combos) == 1
    assert combos[0] == ("SiO2", 5.0)


def test_exp_id_includes_additive(additive_runner: AdditiveBatchJobBinderCellRunner) -> None:
    spec = BatchJobBinderCellSpec(
        binder_types=["AAA1"],
        structure_sizes=["X1"],
        temperatures_k=[293.0],
        aging_states=["non_aging"],
        seeds=[1],
        additive_types=["none", "SiO2"],
        additive_concentrations=[5.0],
    )
    jobs = additive_runner._generate_jobs(spec)
    assert len(jobs) == 2  # control + treatment
    exp_ids = [j.exp_id for j in jobs]
    assert any("_none_" in eid.lower() for eid in exp_ids)
    assert any("_SiO2_" in eid for eid in exp_ids)


def test_validate_no_duplicates(
    additive_runner: AdditiveBatchJobBinderCellRunner, mock_experiment_repo: MagicMock
) -> None:
    mock_experiment_repo.get_by_id.return_value = None
    spec = BatchJobBinderCellSpec(
        binder_types=["AAA1"],
        temperatures_k=[293.0],
        seeds=[1],
        additive_types=["none", "SiO2"],
        additive_concentrations=[5.0],
    )
    result = additive_runner.validate(spec)
    assert result.total == 2
    assert result.new == 2
    assert result.duplicates == 0


def test_submit_dispatches_correct_count(
    additive_runner: AdditiveBatchJobBinderCellRunner,
    mock_job_manager: MagicMock,
) -> None:
    spec = BatchJobBinderCellSpec(
        binder_types=["AAA1"],
        structure_sizes=["X1"],
        temperatures_k=[293.0],
        aging_states=["non_aging"],
        seeds=[1],
        additive_types=["none", "SiO2"],
        additive_concentrations=[5.0],
    )

    result = additive_runner.submit(spec)
    assert result.submitted == 2  # control + treatment
    assert mock_job_manager.submit.call_count == 2


def test_additive_metadata_propagation(
    additive_runner: AdditiveBatchJobBinderCellRunner,
    mock_job_manager: MagicMock,
) -> None:
    spec = BatchJobBinderCellSpec(
        binder_types=["AAA1"],
        temperatures_k=[293.0],
        seeds=[1],
        additive_types=["none", "SiO2"],
        additive_concentrations=[5.0],
    )
    additive_runner.submit(spec)

    kwargs_list = [c.kwargs for c in mock_job_manager.submit.call_args_list]
    # Control call
    assert any(k["additive_type"] is None and k["additive_wt"] == 0.0 for k in kwargs_list)
    # Treatment call
    assert any(k["additive_type"] == "SiO2" and k["additive_wt"] == 5.0 for k in kwargs_list)


def test_additive_submit_persists_e_intra_method_metadata(
    additive_runner: AdditiveBatchJobBinderCellRunner,
) -> None:
    spec = BatchJobBinderCellSpec(
        binder_types=["AAA1"],
        temperatures_k=[293.0],
        seeds=[1],
        additive_types=["none", "SiO2"],
        additive_concentrations=[5.0],
        e_intra_method="single_molecule_vacuum_adaptive_cutoff",
        e_intra_method_source="request",
    )

    with patch("orchestrator.batch_job_binder_cell.SubmissionFacade.submit_experiment") as submit:
        submit.return_value = ("job_001", "task_001")
        result = additive_runner.submit(spec)

    assert result.submitted == 2
    for call in submit.call_args_list:
        metadata = call.kwargs["metadata_json"]
        assert call.kwargs["protocol_request"].e_intra_method == (
            "single_molecule_vacuum_adaptive_cutoff"
        )
        assert metadata["e_intra_method"] == "single_molecule_vacuum_adaptive_cutoff"
        assert metadata["ced_provenance"]["e_intra_method_source"] == "request"


def test_additive_composition_injection_changes_mol_counts(
    additive_runner: AdditiveBatchJobBinderCellRunner,
    mock_job_manager: MagicMock,
) -> None:
    spec = BatchJobBinderCellSpec(
        binder_types=["AAA1"],
        temperatures_k=[293.0],
        seeds=[1],
        additive_types=["none", "SiO2"],
        additive_concentrations=[5.0],
    )
    additive_runner.submit(spec)

    calls = [c.kwargs for c in mock_job_manager.submit.call_args_list]
    control_call = next(c for c in calls if c["additive_type"] is None)
    treatment_call = next(c for c in calls if c["additive_type"] == "SiO2")

    control_comp = control_call["build_request"].composition
    treatment_comp = treatment_call["build_request"].composition
    assert treatment_comp != control_comp


def test_api_batch_job_request_additive_fields() -> None:
    req = BatchJobBinderCellRequest(
        binder_types=["AAA1"],
        additive_types=["SiO2"],
        additive_concentrations=[3.0, 5.0],
    )
    assert req.additive_types == ["SiO2"]
    assert req.additive_concentrations == [3.0, 5.0]


def test_api_batch_job_response_includes_additive_fields() -> None:
    """BatchJobBinderCellJobResponse must round-trip additive fields (Issue #5 regression guard)."""
    from api.schemas import BatchJobBinderCellJobResponse

    # Treatment job — additive fields populated
    resp = BatchJobBinderCellJobResponse(
        exp_id="test_exp",
        binder_type="AAA1",
        structure_size="X1",
        temperature_k=293.0,
        aging_state="non_aging",
        tier="screening",
        status="pending",
        additive_type="SiO2",
        additive_concentration=5.0,
    )
    dumped = resp.model_dump()
    assert dumped["additive_type"] == "SiO2"
    assert dumped["additive_concentration"] == 5.0

    # Control job — additive fields use defaults
    ctrl = BatchJobBinderCellJobResponse(
        exp_id="ctrl_exp",
        binder_type="AAA1",
        structure_size="X1",
        temperature_k=293.0,
        aging_state="non_aging",
        tier="screening",
        status="pending",
    )
    ctrl_dumped = ctrl.model_dump()
    assert ctrl_dumped["additive_type"] is None
    assert ctrl_dumped["additive_concentration"] == 0.0


def test_additive_jobs_are_typed(additive_runner: AdditiveBatchJobBinderCellRunner) -> None:
    spec = BatchJobBinderCellSpec(
        binder_types=["AAA1"],
        temperatures_k=[293.0],
        seeds=[1],
        additive_types=["none", "SiO2"],
        additive_concentrations=[5.0],
    )
    jobs = additive_runner._generate_jobs(spec)
    assert all(isinstance(j, AdditiveBatchJobBinderCellJob) for j in jobs)


def test_fallback_to_base_runner_when_no_additive_axis(
    mock_experiment_repo: MagicMock,
    mock_molecule_db: MagicMock,
    mock_job_manager: MagicMock,
) -> None:
    base = BatchJobBinderCellRunner(
        experiment_repo=mock_experiment_repo,
        molecule_db=mock_molecule_db,
        job_manager=mock_job_manager,
    )
    additive = AdditiveBatchJobBinderCellRunner(
        experiment_repo=mock_experiment_repo,
        molecule_db=mock_molecule_db,
        job_manager=mock_job_manager,
    )

    spec = BatchJobBinderCellSpec(
        binder_types=["AAA1"],
        temperatures_k=[293.0],
        seeds=[1],
        additive_types=[],
        additive_concentrations=[],
    )

    base_jobs = base._generate_jobs(spec)
    additive_jobs = additive._generate_jobs(spec)
    assert len(base_jobs) == len(additive_jobs)


# ── Regression tests for additive loading fix (v00.96.35) ──────────────────


class TestAdditiveLoadingRegression:
    """Regression tests for additive loading fix.

    These tests verify that the unified MoleculeDB loader correctly loads
    additives from the combined config (binder + single + additives).
    """

    def test_helper_creates_molecule_db_with_additives(self) -> None:
        """Helper should create MoleculeDB with additives loaded."""
        from builder.molecule_db_loader import create_molecule_db

        db = create_molecule_db(allow_mock=False)

        # Production smoke test: SiO2 should be loaded from additives.yaml
        assert db.has("SiO2"), "SiO2 should be in MoleculeDB from additives.yaml"

    def test_helper_returns_config_with_additives(self) -> None:
        """Helper should return combined config with additives key."""
        from builder.molecule_db_loader import load_combined_molecule_config_strict

        config = load_combined_molecule_config_strict()

        assert "additives" in config, "Config must have 'additives' key"
        assert len(config["additives"]) > 0, "Additives should not be empty"
        assert "SiO2" in config["additives"], "SiO2 should be in additives"

    def test_batch_runner_config_has_additives(self, mock_experiment_repo: MagicMock) -> None:
        """BatchJobBinderCellRunner._get_config() should have additives."""
        runner = BatchJobBinderCellRunner(experiment_repo=mock_experiment_repo)
        config = runner._get_config()

        assert "additives" in config, "Config must have 'additives' key"
        assert len(config["additives"]) > 0, "Additives should not be empty"

    def test_batch_runner_molecule_db_has_production_additives(
        self, mock_experiment_repo: MagicMock
    ) -> None:
        """BatchJobBinderCellRunner._get_molecule_db() should include production additives."""
        runner = BatchJobBinderCellRunner(experiment_repo=mock_experiment_repo)
        db = runner._get_molecule_db()

        # Production smoke test: SiO2 should be loaded
        assert db.has("SiO2"), "SiO2 should be loaded from production additives.yaml"

    def test_additive_runner_config_has_additives(
        self, mock_experiment_repo: MagicMock, mock_job_manager: MagicMock
    ) -> None:
        """AdditiveBatchJobBinderCellRunner._get_config() should have additives."""
        runner = AdditiveBatchJobBinderCellRunner(
            experiment_repo=mock_experiment_repo,
            job_manager=mock_job_manager,
        )
        config = runner._get_config()

        assert "additives" in config, "Config must have 'additives' key"
        assert "SiO2" in config["additives"], "SiO2 should be in additives"

    def test_inject_additive_adds_to_composition_when_db_has_additive(
        self, mock_experiment_repo: MagicMock, mock_job_manager: MagicMock
    ) -> None:
        """When db.has(additive)=True, additive should be in composition."""
        runner = AdditiveBatchJobBinderCellRunner(
            experiment_repo=mock_experiment_repo,
            job_manager=mock_job_manager,
            # Use real MoleculeDB (no mock) to test actual loading
        )

        config = runner._get_config()
        base_composition = {"U-SA-Squalane-0293": 10, "U-SA-Hopane-0293": 10}

        # Find an additive that is loaded
        for additive_id in config.get("additives", {}):
            if runner._get_molecule_db().has(additive_id):
                modified = runner._inject_additive_into_composition(
                    base_composition=base_composition,
                    additive_type=additive_id,
                    additive_concentration=5.0,
                    config=config,
                    structure_size="X1",
                )
                assert additive_id in modified, f"Additive '{additive_id}' should be in composition"
                break
        else:
            # No additive found in DB - this should not happen with proper loading
            pytest.fail("No loaded additive found for injection test - loading may be broken")


# ── Isolated fixture tests for loader contract verification (v00.96.35) ────


class TestLoaderContractIsolated:
    """Isolated tests for loader contract using temporary fixtures.

    These tests do not depend on production data and verify:
    - Config merging logic (binder + single + additives)
    - Exception handling paths (YAML errors, .mol errors)
    - allow_mock fallback behavior
    """

    @pytest.fixture
    def minimal_config_dir(self, tmp_path: Path) -> Path:
        """Create minimal molecule config files in tmp_path."""
        # asphalt_binder.yaml - minimal valid config
        binder = tmp_path / "asphalt_binder.yaml"
        binder.write_text("""
library:
  name: test_binder
molecules:
  - base_id: SA-TestMol
    name: TestMolecule
    sara: saturate
    atom_count: 10
    molecular_weight: 100.0
    available_aging: [non_aging]
aging_categories:
  non_aging:
    directory: test_moles
    prefix: U
structure_sizes:
  X1: {target_atoms: 100000}
binder_types:
  TestBinder:
    base_molecules:
      SA-TestMol: 100.0
""")
        # single_moles.yaml - empty but valid
        single = tmp_path / "single_moles.yaml"
        single.write_text("molecules: []")

        # additives.yaml - with test additive
        additives = tmp_path / "additives.yaml"
        additives.write_text("""
additives:
  TestAdditive:
    name: Test Additive
    short_name: TA
    atom_count: 2
    molecular_weight: 28.0
    counts:
      X1: 2
    category: test
    structure_file: additives/TestAdditive.mol
""")
        # Create structure directories and files
        (tmp_path / "test_moles").mkdir()
        mol_content = """TestMol
  test

  2  1  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    1.5000    0.0000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0  0  0  0
M  END
"""
        (tmp_path / "test_moles" / "U-SA-TestMol.mol").write_text(mol_content)

        (tmp_path / "additives").mkdir()
        (tmp_path / "additives" / "TestAdditive.mol").write_text(mol_content)

        return tmp_path

    def test_combined_config_merges_additives(self, minimal_config_dir: Path) -> None:
        """load_combined_molecule_config should merge additives into result."""
        from unittest.mock import patch

        with patch(
            "common.library_config.get_molecule_data_dir",
            return_value=minimal_config_dir,
        ):
            from common.library_config import load_combined_molecule_config

            config = load_combined_molecule_config()

            assert "additives" in config
            assert "TestAdditive" in config["additives"]
            assert config["additives"]["TestAdditive"]["name"] == "Test Additive"

    def test_loader_allow_mock_on_yaml_parse_error(self, tmp_path: Path) -> None:
        """allow_mock=True should fallback to mock on YAML parse error."""
        from unittest.mock import patch

        # Create invalid YAML
        binder = tmp_path / "asphalt_binder.yaml"
        binder.write_text("invalid: yaml: content: [")

        with (
            patch(
                "builder.molecule_db_loader.get_asphalt_binder_config_path",
                return_value=binder,
            ),
            patch(
                "builder.molecule_db_loader.get_project_root",
                return_value=tmp_path,
            ),
        ):
            from builder.molecule_db_loader import create_molecule_db

            # Should not raise, should fallback to mock
            db = create_molecule_db(allow_mock=True)
            assert db is not None

    def test_loader_strict_raises_on_yaml_parse_error(self, tmp_path: Path) -> None:
        """allow_mock=False should raise RuntimeError on YAML parse error."""
        from unittest.mock import patch

        # Create invalid YAML
        binder = tmp_path / "asphalt_binder.yaml"
        binder.write_text("invalid: yaml: content: [")

        with (
            patch(
                "builder.molecule_db_loader.get_asphalt_binder_config_path",
                return_value=binder,
            ),
            patch(
                "builder.molecule_db_loader.get_project_root",
                return_value=tmp_path,
            ),
            patch(
                "common.library_config.get_molecule_data_dir",
                return_value=tmp_path,
            ),
        ):
            from builder.molecule_db_loader import create_molecule_db

            with pytest.raises(RuntimeError, match="Failed to load molecule config"):
                create_molecule_db(allow_mock=False)

    def test_loader_allow_mock_on_missing_config(self, tmp_path: Path) -> None:
        """allow_mock=True should fallback to mock when config file missing."""
        from unittest.mock import patch

        missing_path = tmp_path / "nonexistent.yaml"

        with patch(
            "builder.molecule_db_loader.get_asphalt_binder_config_path",
            return_value=missing_path,
        ):
            from builder.molecule_db_loader import create_molecule_db

            db = create_molecule_db(allow_mock=True)
            assert db is not None

    def test_loader_strict_raises_on_missing_config(self, tmp_path: Path) -> None:
        """allow_mock=False should raise RuntimeError when config missing."""
        from unittest.mock import patch

        missing_path = tmp_path / "nonexistent.yaml"

        with patch(
            "builder.molecule_db_loader.get_asphalt_binder_config_path",
            return_value=missing_path,
        ):
            from builder.molecule_db_loader import create_molecule_db

            with pytest.raises(RuntimeError, match="Molecule config not found"):
                create_molecule_db(allow_mock=False)

    def test_deprecated_config_path_logs_warning(
        self, mock_experiment_repo: MagicMock, caplog
    ) -> None:
        """Passing config_path should log deprecation warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            BatchJobBinderCellRunner(
                experiment_repo=mock_experiment_repo,
                config_path=Path("/custom/path.yaml"),
            )

        assert "deprecated" in caplog.text.lower()
        assert "ignored" in caplog.text.lower()
