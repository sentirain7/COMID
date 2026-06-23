"""
Pytest configuration and fixtures for test suite.
"""

import shutil
import sys
import tempfile
from collections.abc import Generator
from datetime import datetime
from pathlib import Path

import pytest

# Add src and packages to Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "packages"))


# =============================================================================
# Pytest Configuration
# =============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "external: marks tests as requiring external services (deselect with '-m \"not external\"')",
    )
    config.addinivalue_line("markers", "slow: marks tests as slow running")


# =============================================================================
# Database Fixtures
# =============================================================================


@pytest.fixture(scope="function")
def db_session() -> Generator:
    """
    Create an isolated in-memory database session for testing.

    Each test gets a fresh database with all tables created.
    """
    from database.connection import close_db, init_memory_db

    session = init_memory_db()
    yield session
    session.close()
    close_db()


@pytest.fixture(scope="function")
def sample_experiments(db_session) -> list:
    """
    Insert sample experiments into the test database.

    Returns list of created experiment IDs.
    """
    from database.models import ExperimentModel

    experiments = []
    for i in range(5):
        exp = ExperimentModel(
            exp_id=f"exp_test_{i + 1:03d}",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="completed" if i < 3 else "running",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            composition_error_l1=0.01,
            target_atoms=100000,
            actual_atoms=99850,
            seed=42 + i,
            topology_hash=f"topo{i:04d}",
            protocol_hash=f"prot{i:04d}",
            temperature_K=298.0,
            pressure_atm=1.0,
            created_at=datetime.utcnow(),
        )
        db_session.add(exp)
        experiments.append(exp.exp_id)

    db_session.commit()
    return experiments


@pytest.fixture(scope="function")
def sample_metrics(db_session, sample_experiments) -> list:
    """
    Insert sample metrics for test experiments.

    Returns list of created metric IDs.
    """
    from database.models import MetricModel

    metrics = []
    for exp_id in sample_experiments[:3]:  # Only completed experiments
        # Density metric
        density = MetricModel(
            exp_id=exp_id,
            metric_name="density",
            namespace="bulk_ff_gaff2",
            value=1.02,
            unit="g/cm3",
            created_at=datetime.utcnow(),
        )
        db_session.add(density)
        metrics.append(f"{exp_id}:density")

        # CED metric
        ced = MetricModel(
            exp_id=exp_id,
            metric_name="cohesive_energy_density",
            namespace="bulk_ff_gaff2",
            value=350.0,
            unit="MJ/m3",
            created_at=datetime.utcnow(),
        )
        db_session.add(ced)
        metrics.append(f"{exp_id}:ced")

    db_session.commit()
    return metrics


@pytest.fixture(scope="function")
def sample_molecules(db_session) -> list:
    """
    Insert sample molecules into the test database.

    Returns list of created molecule IDs.
    """
    from database.models import MoleculeModel

    molecules_data = [
        {
            "mol_id": "SAT_001",
            "name": "hexadecane",
            "smiles": "CCCCCCCCCCCCCCCC",
            "molecular_weight": 226.44,
            "atom_count": 50,
            "sara_type": "saturate",
        },
        {
            "mol_id": "ARO_001",
            "name": "naphthalene",
            "smiles": "c1ccc2ccccc2c1",
            "molecular_weight": 128.17,
            "atom_count": 18,
            "sara_type": "aromatic",
        },
        {
            "mol_id": "RES_001",
            "name": "benzothiophene",
            "smiles": "c1ccc2sccc2c1",
            "molecular_weight": 134.20,
            "atom_count": 15,
            "sara_type": "resin",
        },
        {
            "mol_id": "ASP_001",
            "name": "coronene",
            "smiles": "c1cc2ccc3ccc4ccc5ccc6ccc1c7c2c3c4c5c67",
            "molecular_weight": 300.35,
            "atom_count": 36,
            "sara_type": "asphaltene",
        },
    ]

    mol_ids = []
    for data in molecules_data:
        mol = MoleculeModel(
            mol_id=data["mol_id"],
            name=data["name"],
            smiles=data["smiles"],
            molecular_weight=data["molecular_weight"],
            atom_count=data["atom_count"],
            sara_type=data["sara_type"],
            created_at=datetime.utcnow(),
        )
        db_session.add(mol)
        mol_ids.append(data["mol_id"])

    db_session.commit()
    return mol_ids


# =============================================================================
# Mock Fixtures for External Services
# =============================================================================


@pytest.fixture
def mock_celery_task():
    """
    Mock Celery task for API tests.

    Prevents actual Redis/Celery connections.
    """
    from unittest.mock import MagicMock, patch

    mock_result = MagicMock()
    mock_result.id = "mock-celery-task-12345"
    mock_result.status = "PENDING"
    mock_result.ready.return_value = False

    with patch("orchestrator.tasks.run_simulation.apply_async", return_value=mock_result):
        with patch("orchestrator.tasks.run_simulation.delay", return_value=mock_result):
            yield mock_result


@pytest.fixture
def project_root() -> Path:
    """Return project root directory."""
    return PROJECT_ROOT


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    tmp = Path(tempfile.mkdtemp(prefix="asphalt_test_"))
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def smoke_test_config() -> dict:
    """
    Configuration for E2E smoke test.

    Uses 10k atoms for quick testing (vs 100k for real screening).
    """
    return {
        "target_atoms": 10000,
        "composition": {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        },
        "temperature_K": 298.0,
        "pressure_atm": 1.0,
        "seed": 20260126,
        "minimize_steps": 100,
        "nvt_ps": 50,
        "npt_ps": 100,
    }


@pytest.fixture
def mock_molecules(temp_dir: Path) -> dict[str, Path]:
    """
    Create mock molecule XYZ files for testing.

    Returns dict of category -> file path.
    """
    molecules = {}

    # Simple mock molecules (C atom clusters)
    mol_data = {
        "asphaltene": {
            "atoms": 42,
            "weight": 278.35,  # g/mol approximate
        },
        "resin": {
            "atoms": 28,
            "weight": 185.0,
        },
        "aromatic": {
            "atoms": 18,
            "weight": 128.0,
        },
        "saturate": {
            "atoms": 20,
            "weight": 142.0,
        },
    }

    mol_dir = temp_dir / "molecules"
    mol_dir.mkdir(parents=True, exist_ok=True)

    for mol_name, data in mol_data.items():
        mol_file = mol_dir / f"{mol_name}.xyz"

        # Generate simple XYZ content
        lines = [str(data["atoms"]), f"Mock {mol_name} molecule"]

        import random

        random.seed(42)
        for _i in range(data["atoms"]):
            x = random.uniform(0, 5)
            y = random.uniform(0, 5)
            z = random.uniform(0, 5)
            lines.append(f"C {x:.6f} {y:.6f} {z:.6f}")

        mol_file.write_text("\n".join(lines))
        molecules[mol_name] = mol_file

    return molecules


@pytest.fixture
def mock_lammps_log() -> Path:
    """
    Create a mock LAMMPS log file with realistic thermo output.
    Uses separate temp directory to avoid conflicts.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="lammps_log_"))
    log_file = tmp_dir / "log.lammps"

    log_content = """LAMMPS (29 Aug 2024)
OMP_NUM_THREADS environment is not set.
  using 1 OpenMP thread(s) per MPI task

Reading data file ...
  orthogonal box = (0 0 0) to (80 80 80)
  10000 atoms

Neighbor list info ...
  update: every = 1 steps, delay = 5 steps, check = yes

Setting up Verlet run ...
  Unit style    : real
  Current step  : 0
  Time step     : 1

Step Temp PotEng KinEng TotEng Press Volume Density
       0     298.0   -5000.0    2000.0   -3000.0    500.0   512000.0    0.95
     100     302.5   -4950.0    2030.0   -2920.0    480.0   510000.0    0.96
     200     300.1   -4920.0    2015.0   -2905.0    490.0   508000.0    0.97
     300     299.5   -4900.0    2010.0   -2890.0    495.0   507000.0    0.98
     400     298.8   -4880.0    2005.0   -2875.0    500.0   506000.0    0.99
     500     298.2   -4870.0    2002.0   -2868.0    502.0   505500.0    1.00
     600     298.0   -4860.0    2000.0   -2860.0    503.0   505000.0    1.01
     700     297.9   -4855.0    1998.0   -2857.0    504.0   504800.0    1.01
     800     298.1   -4852.0    2001.0   -2851.0    505.0   504600.0    1.02
     900     298.0   -4850.0    2000.0   -2850.0    505.5   504500.0    1.02
    1000     298.0   -4848.0    2000.0   -2848.0    506.0   504400.0    1.02
Loop time of 120.5 on 1 procs for 1000 steps with 10000 atoms

Performance: 0.717 ns/day, 33.472 hours/ns, 8.299 timesteps/s
Total wall time: 0:02:00
"""
    log_file.write_text(log_content)
    yield log_file
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def lammps_available() -> bool:
    """Check if LAMMPS is available."""
    from common.tooling import resolve_lammps_executable

    return resolve_lammps_executable() is not None


@pytest.fixture
def packmol_available() -> bool:
    """Check if Packmol is available."""
    from common.tooling import resolve_packmol_executable

    return resolve_packmol_executable() is not None
