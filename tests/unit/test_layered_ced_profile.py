"""Tests for layered cohesive_energy_density_profile wiring."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from common.units import energy_to_ced
from contracts.schema_enums import FFType, RunTier
from contracts.schemas import (
    GroupEnergySpec,
    GroupSelector,
    LAMMPSRunResult,
    ProtocolRequest,
    StudyType,
)
from metrics.array_storage import ArrayStorage
from metrics.calculator import MetricCalculator
from protocols.lammps_input import LAMMPSInputGenerator


def _write_minimal_data_file(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "LAMMPS data file - test",
                "",
                "2 atoms",
                "0 bonds",
                "0 angles",
                "0 dihedrals",
                "0 impropers",
                "",
                "1 atom types",
                "0 bond types",
                "0 angle types",
                "0 dihedral types",
                "0 improper types",
                "",
                "0.0 20.0 xlo xhi",
                "0.0 20.0 ylo yhi",
                "0.0 20.0 zlo zhi",
                "",
                "Masses",
                "",
                "1 12.011",
                "",
                "Atoms # full",
                "",
                "1 1 1 0.0 1.0 1.0 1.0",
                "2 2 1 0.0 2.0 2.0 2.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


class _FakeEIntraStore:
    def __init__(self, mapping: dict[str, float]):
        self.mapping = mapping

    def get(self, key):  # noqa: ANN001 - interface shim for tests
        if key.mol_id not in self.mapping:
            return None
        return SimpleNamespace(e_intra=self.mapping[key.mol_id], temperature_K=key.temperature_K)


def _write_layered_log(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "LAMMPS (1 Jan 2025)",
                "Step Temp Press PotEng KinEng TotEng Volume Density c_pe_layer_0 c_pe_layer_1",
                "0 298.0 1.0 -120.0 10.0 -110.0 1000.0 0.001 -40.0 -60.0",
                "1000 298.0 1.0 -120.0 10.0 -110.0 1000.0 0.001 -40.0 -60.0",
                "Loop time of 1.0 on 1 procs",
                "Total wall time: 0:00:01",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_lammps_input_generator_emits_layer_pe_commands(tmp_path: Path) -> None:
    data_path = tmp_path / "layer.data"
    _write_minimal_data_file(data_path)

    spec = GroupEnergySpec(
        group_selectors={
            "layer_0": GroupSelector(mode="atom_id_range", range_start=1, range_end=1),
            "layer_1": GroupSelector(mode="atom_id_range", range_start=2, range_end=2),
        },
        layer_count=2,
    )
    request = ProtocolRequest(
        run_tier=RunTier.SCREENING,
        ff_type=FFType.BULK_FF_GAFF2,
        study_type=StudyType.LAYER_BULKFF,
        temperature_K=298.0,
        pressure_atm=1.0,
        data_file_path=str(data_path),
        e_intra_method="single_molecule_vacuum_adaptive_cutoff",
        group_energy_spec=spec,
    )
    generator = LAMMPSInputGenerator(template_dir=tmp_path / "templates")

    result = generator.generate(request)
    text = Path(result.input_script_path).read_text(encoding="utf-8")

    assert "compute pe_layer_atoms all pe/atom" in text
    assert "compute pe_layer_0 layer_0 reduce sum c_pe_layer_atoms" in text
    assert "compute pe_layer_1 layer_1 reduce sum c_pe_layer_atoms" in text
    assert "c_pe_layer_0" in text
    assert "c_pe_layer_1" in text


def test_metric_calculator_creates_layered_ced_profile(tmp_path: Path) -> None:
    log_path = tmp_path / "log.lammps"
    _write_layered_log(log_path)
    store = _FakeEIntraStore({"mol_A": -10.0, "mol_B": -5.0})
    array_storage = ArrayStorage(storage_dir=tmp_path / "arrays")
    calc = MetricCalculator(e_intra_store=store, array_storage=array_storage)

    run_result = LAMMPSRunResult(
        success=True,
        log_file=str(log_path),
        dump_files=[],
        wall_time_seconds=1.0,
        exit_code=0,
        exp_id="exp_layer_profile",
        study_type="layer_bulkff",
        temperature_K=298.0,
        force_field="GAFF2",
        ff_version="1.0",
        e_intra_method="single_molecule_vacuum_adaptive_cutoff",
        mol_counts={"mol_A": 1, "mol_B": 2},
        mol_counts_by_layer={
            "layer_0": {"mol_A": 1},
            "layer_1": {"mol_B": 2},
        },
        layer_volumes_A3={"layer_0": 400.0, "layer_1": 600.0},
        layer_labels=["layer_0", "layer_1"],
    )

    metrics = calc.calculate(run_result)
    profile = next((m for m in metrics if m.metric_name == "cohesive_energy_density_profile"), None)

    assert profile is not None
    assert profile.array_storage is not None
    data = array_storage.load("cohesive_energy_density_profile", "exp_layer_profile")
    assert data is not None
    assert data["layer_label"] == ["layer_0", "layer_1"]
    assert len(data["ced_MJ_m3"]) == 2
    assert data["ced_MJ_m3"][0] == energy_to_ced(-30.0, 400.0)
    assert data["ced_MJ_m3"][1] == energy_to_ced(-50.0, 600.0)
    assert profile.array_summary["profile_scope"] == "binder_backed_layers"


def test_metric_calculator_skips_layered_profile_when_e_intra_missing(tmp_path: Path) -> None:
    log_path = tmp_path / "log_missing.lammps"
    _write_layered_log(log_path)
    store = _FakeEIntraStore({"mol_A": -10.0})
    calc = MetricCalculator(e_intra_store=store, array_storage=ArrayStorage(tmp_path / "arrays2"))

    run_result = LAMMPSRunResult(
        success=True,
        log_file=str(log_path),
        dump_files=[],
        wall_time_seconds=1.0,
        exit_code=0,
        exp_id="exp_layer_profile_missing",
        study_type="layer_bulkff",
        temperature_K=298.0,
        force_field="GAFF2",
        ff_version="1.0",
        e_intra_method="single_molecule_vacuum_adaptive_cutoff",
        mol_counts={"mol_A": 1, "mol_B": 2},
        mol_counts_by_layer={
            "layer_0": {"mol_A": 1},
            "layer_1": {"mol_B": 2},
        },
        layer_volumes_A3={"layer_0": 400.0, "layer_1": 600.0},
        layer_labels=["layer_0", "layer_1"],
    )

    metrics = calc.calculate(run_result)

    assert "cohesive_energy_density_profile" not in [m.metric_name for m in metrics]
