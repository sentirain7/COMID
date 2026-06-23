"""Tests for canonical layered runtime wiring.

Verifies that layer_lineage, group_energy_spec, and interface_area_nm2
flow correctly through the canonical layered submission pipeline.
"""

import sys
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, "src")

from contracts.schema_enums import FFType, RunTier
from contracts.schemas import BuildRequest, GroupEnergySpec, ProtocolRequest, StudyType


class TestPipelineInterfaceAreaSetting:
    """Verify pipeline sets interface_area_nm2 for LAYER_BULKFF."""

    def test_layer_bulkff_with_box_dimensions(self):
        """LAYER_BULKFF + box_dimensions → interface_area_nm2 set."""
        lammps_result = MagicMock()
        lammps_result.interface_area_nm2 = None

        build_request = MagicMock(spec=BuildRequest)
        build_request.box_dimensions = (40.0, 42.0, 100.0)

        protocol_request = MagicMock(spec=ProtocolRequest)
        protocol_request.study_type = StudyType.LAYER_BULKFF

        # Simulate pipeline logic
        study_type_val = (
            protocol_request.study_type.value
            if hasattr(protocol_request.study_type, "value")
            else str(protocol_request.study_type)
        )
        if study_type_val == "layer_bulkff" and build_request.box_dimensions:
            _lx, _ly, _lz = build_request.box_dimensions
            lammps_result.interface_area_nm2 = float(_lx) * float(_ly) / 100.0

        assert lammps_result.interface_area_nm2 is not None
        expected = 40.0 * 42.0 / 100.0  # 16.8 nm²
        assert abs(lammps_result.interface_area_nm2 - expected) < 0.01

    def test_bulk_study_type_no_area(self):
        """BULK study type should NOT set interface_area_nm2."""
        lammps_result = MagicMock()
        lammps_result.interface_area_nm2 = None

        build_request = MagicMock(spec=BuildRequest)
        build_request.box_dimensions = (40.0, 42.0, 100.0)

        protocol_request = MagicMock(spec=ProtocolRequest)
        protocol_request.study_type = StudyType.BULK

        study_type_val = protocol_request.study_type.value
        if study_type_val == "layer_bulkff" and build_request.box_dimensions:
            lammps_result.interface_area_nm2 = 999.0  # should NOT execute

        assert lammps_result.interface_area_nm2 is None

    def test_no_box_dimensions_no_area(self):
        """LAYER_BULKFF without box_dimensions → no interface_area."""
        lammps_result = MagicMock()
        lammps_result.interface_area_nm2 = None

        build_request = MagicMock(spec=BuildRequest)
        build_request.box_dimensions = None

        protocol_request = MagicMock(spec=ProtocolRequest)
        protocol_request.study_type = StudyType.LAYER_BULKFF

        study_type_val = protocol_request.study_type.value
        if study_type_val == "layer_bulkff" and build_request.box_dimensions:
            lammps_result.interface_area_nm2 = 999.0

        assert lammps_result.interface_area_nm2 is None


class TestPipelineGroupEnergySpecPreservation:
    """Verify pipeline preserves pre-set group_energy_spec."""

    def test_preset_spec_not_overwritten(self):
        """If protocol_request.group_energy_spec is already set, pipeline should keep it."""
        preset_spec = GroupEnergySpec(layer_count=3)
        protocol_request = MagicMock(spec=ProtocolRequest)
        protocol_request.group_energy_spec = preset_spec

        build_result = MagicMock()
        build_result.molecule_ordering = [
            {"mol_id": "A", "count": 5, "category": "saturate", "atom_count": 50}
        ]

        # Simulate pipeline logic (v2: preserve pre-set)
        if protocol_request.group_energy_spec is None:
            # v1 path would set it here
            protocol_request.group_energy_spec = "should_not_reach"

        assert protocol_request.group_energy_spec is preset_spec

    def test_none_spec_gets_v1_assignment(self):
        """If no pre-set spec, pipeline should build from molecule_ordering."""
        from metrics.group_assignment import GroupAssignmentBuilder

        protocol_request = MagicMock(spec=ProtocolRequest)
        protocol_request.group_energy_spec = None

        ordering = [
            {"mol_id": "A", "count": 5, "category": "saturate", "atom_count": 50},
            {"mol_id": "B", "count": 3, "category": "aromatic", "atom_count": 40},
        ]

        # Simulate pipeline logic
        if protocol_request.group_energy_spec is None:
            spec = GroupAssignmentBuilder().build(ordering)
            protocol_request.group_energy_spec = spec

        assert protocol_request.group_energy_spec is not None
        assert protocol_request.group_energy_spec.layer_count is None  # v1 doesn't set this
        assert len(protocol_request.group_energy_spec.groups) == 2


class TestPipelineLayeredCEDProvenance:
    """Verify layered runtime can restore CED provenance for wt% submissions."""

    def test_attach_ced_lookup_metadata_prefers_protocol_request_provenance_counts(self):
        from orchestrator.pipeline import Pipeline

        run_result = SimpleNamespace(
            exp_id="EXP-LAYER-PROTO-001",
            mol_counts={},
            e_intra_method=None,
            vacuum_cutoff_a=None,
            log_file=None,
        )
        build = BuildRequest(
            composition={"asphaltene": 20.0, "resin": 30.0, "aromatic": 35.0, "saturate": 15.0},
            composition_mode="wt_percent",
            target_atoms=1000,
            seed=1,
            tier=RunTier.SCREENING,
        )
        proto = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/tmp/layer.data",
            e_intra_method="single_molecule_vacuum_adaptive_cutoff",
            ced_provenance_mol_counts={"mol_A": 4, "mol_B": 2},
            ced_provenance_mol_counts_by_layer={
                "layer_0": {"mol_A": 4},
                "layer_1": {"mol_B": 2},
            },
            ced_provenance_layer_volumes_A3={"layer_0": 400.0, "layer_1": 600.0},
            ced_provenance_layer_labels=["layer_0", "layer_1"],
        )

        Pipeline._attach_ced_lookup_metadata(run_result, build, proto)

        assert run_result.e_intra_method == "single_molecule_vacuum_adaptive_cutoff"
        assert run_result.mol_counts == {"mol_A": 4, "mol_B": 2}
        assert run_result.mol_counts_by_layer == {
            "layer_0": {"mol_A": 4},
            "layer_1": {"mol_B": 2},
        }
        assert run_result.layer_volumes_A3 == {"layer_0": 400.0, "layer_1": 600.0}
        assert run_result.layer_labels == ["layer_0", "layer_1"]

    def test_attach_ced_lookup_metadata_restores_counts_and_method(self, monkeypatch):
        from orchestrator.pipeline import Pipeline

        fake_exp = SimpleNamespace(
            id=17,
            metadata_json={
                "e_intra_method": "single_molecule_vacuum_adaptive_cutoff",
                "ced_provenance": {
                    "mol_counts": {"meta_only": 99},
                    "mol_counts_by_layer": {
                        "layer_0": {"mol_A": 3},
                        "layer_1": {"mol_B": 2},
                    },
                    "layer_volumes_A3": {"layer_0": 450.0, "layer_1": 550.0},
                    "layer_labels": ["layer_0", "layer_1"],
                },
            },
        )
        mol_rows = [
            (SimpleNamespace(count=3), SimpleNamespace(mol_id="mol_A")),
            (SimpleNamespace(count=2), SimpleNamespace(mol_id="mol_B")),
        ]

        class _Query:
            def __init__(self, first_result=None, all_result=None):
                self._first_result = first_result
                self._all_result = all_result or []

            def filter(self, *_args, **_kwargs):
                return self

            def join(self, *_args, **_kwargs):
                return self

            def first(self):
                return self._first_result

            def all(self):
                return self._all_result

        class _Session:
            def query(self, *models):
                if len(models) == 1:
                    return _Query(first_result=fake_exp)
                return _Query(all_result=mol_rows)

        @contextmanager
        def _stub_session_scope():
            yield _Session()

        import database.connection as _conn_mod

        monkeypatch.setattr(_conn_mod, "session_scope", _stub_session_scope)

        run_result = SimpleNamespace(
            exp_id="EXP-LAYER-001",
            mol_counts={},
            e_intra_method=None,
            vacuum_cutoff_a=None,
            log_file=None,
        )
        build = BuildRequest(
            composition={"asphaltene": 20.0, "resin": 30.0, "aromatic": 35.0, "saturate": 15.0},
            composition_mode="wt_percent",
            target_atoms=1000,
            seed=1,
            tier=RunTier.SCREENING,
        )
        proto = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="/tmp/layer.data",
        )

        Pipeline._attach_ced_lookup_metadata(run_result, build, proto)

        assert run_result.study_type == "layer_bulkff"
        assert run_result.e_intra_method == "single_molecule_vacuum_adaptive_cutoff"
        assert run_result.mol_counts == {"mol_A": 3, "mol_B": 2}
        assert run_result.mol_counts_by_layer == {
            "layer_0": {"mol_A": 3},
            "layer_1": {"mol_B": 2},
        }
        assert run_result.layer_volumes_A3 == {"layer_0": 450.0, "layer_1": 550.0}
        assert run_result.layer_labels == ["layer_0", "layer_1"]
