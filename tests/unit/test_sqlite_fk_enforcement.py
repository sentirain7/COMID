"""Tests for SQLite FK enforcement and ORM cascade delete.

Validates:
1. PRAGMA foreign_keys=ON is enabled for all SQLite connections
2. FK violations raise IntegrityError
3. ON DELETE CASCADE works correctly via DDL
4. FFConditionKey enum provides SSOT for condition keys
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


class TestSQLiteFKPragma:
    """Tests for SQLite foreign key pragma enforcement."""

    def test_sqlite_fk_pragma_enabled(self, db_session):
        """init_memory_db() session should have PRAGMA foreign_keys=1."""
        result = db_session.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1, "FK enforcement should be enabled"

    def test_fk_violation_raises_integrity_error(self, db_session):
        """Insert with non-existent FK should raise IntegrityError."""
        from database.models import ExperimentConditionModel

        with pytest.raises(IntegrityError):
            cond = ExperimentConditionModel(
                experiment_id=99999,  # Non-existent experiment
                condition_key="test.key",
                value_type="text",
                value_text="test_value",
            )
            db_session.add(cond)
            db_session.commit()


class TestORMCascadeDelete:
    """Tests for ON DELETE CASCADE DDL enforcement."""

    def test_cascade_delete_experiment_conditions(self, db_session):
        """Deleting experiment should cascade-delete its conditions."""
        from database.models import ExperimentConditionModel, ExperimentModel

        # Create experiment
        exp = ExperimentModel(
            exp_id="cascade_test_001",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            status="pending",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(exp)
        db_session.flush()

        # Add conditions
        cond1 = ExperimentConditionModel(
            experiment_id=exp.id,
            condition_key="ff.stack_id",
            value_type="text",
            value_text="gaff2_am1bcc_v1",
        )
        cond2 = ExperimentConditionModel(
            experiment_id=exp.id,
            condition_key="ff.lane_id",
            value_type="text",
            value_text="bulk_organic",
        )
        db_session.add_all([cond1, cond2])
        db_session.commit()

        # Verify conditions exist
        count_before = (
            db_session.query(ExperimentConditionModel).filter_by(experiment_id=exp.id).count()
        )
        assert count_before == 2

        # Delete experiment via session (ORM cascade + DDL cascade)
        db_session.delete(exp)
        db_session.commit()

        # Conditions should be gone (DDL CASCADE)
        count_after = (
            db_session.query(ExperimentConditionModel).filter_by(experiment_id=exp.id).count()
        )
        assert count_after == 0

    def test_cascade_delete_experiment_molecules(self, db_session):
        """Deleting experiment should cascade-delete experiment_molecules rows."""
        from database.models import ExperimentModel, ExperimentMoleculeModel, MoleculeModel

        # Create molecule directly (avoiding sample_molecules fixture issue)
        mol = MoleculeModel(
            mol_id="TEST_MOL_001",
            smiles="CCCCCCCCCCCCCCCC",
            name="test_molecule",
            sara_type="saturate",
            molecular_weight=226.0,
            num_atoms=50,
        )
        db_session.add(mol)
        db_session.flush()

        # Create experiment
        exp = ExperimentModel(
            exp_id="cascade_mol_test_001",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            status="pending",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(exp)
        db_session.flush()

        # Link molecule to experiment
        link = ExperimentMoleculeModel(
            experiment_id=exp.id,
            molecule_id=mol.id,
            count=5,
        )
        db_session.add(link)
        db_session.commit()

        # Verify link exists
        count_before = (
            db_session.query(ExperimentMoleculeModel).filter_by(experiment_id=exp.id).count()
        )
        assert count_before == 1

        # Delete experiment
        db_session.delete(exp)
        db_session.commit()

        # Link should be gone (CASCADE delete)
        count_after = (
            db_session.query(ExperimentMoleculeModel).filter_by(experiment_id=exp.id).count()
        )
        assert count_after == 0

    def test_cascade_delete_process_info(self, db_session):
        """Deleting experiment should cascade-delete process_info."""
        from database.models import ExperimentModel, ProcessInfoModel

        # Create experiment
        exp = ExperimentModel(
            exp_id="cascade_proc_test_001",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            status="running",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(exp)
        db_session.commit()

        # Add process info
        proc = ProcessInfoModel(
            exp_id=exp.exp_id,
            pid=12345,
            hostname="test-host",
            working_dir="/tmp/test",
            gpu_id=0,
        )
        db_session.add(proc)
        db_session.commit()

        # Verify process info exists
        proc_count = db_session.query(ProcessInfoModel).filter_by(exp_id=exp.exp_id).count()
        assert proc_count == 1

        # Delete experiment
        db_session.delete(exp)
        db_session.commit()

        # Process info should be gone
        proc_count_after = (
            db_session.query(ProcessInfoModel).filter_by(exp_id="cascade_proc_test_001").count()
        )
        assert proc_count_after == 0


class TestFFConditionKeySSoT:
    """Tests for FFConditionKey enum and helper functions."""

    def test_list_ff_condition_keys_returns_9(self):
        """list_ff_condition_keys() should return exactly 9 keys."""
        from contracts.policies.forcefield import list_ff_condition_keys

        keys = list_ff_condition_keys()
        assert len(keys) == 9, f"Expected 9 keys, got {len(keys)}: {keys}"

    def test_ff_condition_keys_all_prefixed(self):
        """All FF condition keys should be prefixed with 'ff.'."""
        from contracts.policies.forcefield import list_ff_condition_keys

        keys = list_ff_condition_keys()
        for key in keys:
            assert key.startswith("ff."), f"Key {key} should start with 'ff.'"

    def test_is_valid_ff_condition_key(self):
        """is_valid_ff_condition_key() validates keys correctly."""
        from contracts.policies.forcefield import is_valid_ff_condition_key

        # Valid keys
        assert is_valid_ff_condition_key("ff.stack_id") is True
        assert is_valid_ff_condition_key("ff.lane_id") is True
        assert is_valid_ff_condition_key("ff.validation_level") is True

        # Invalid keys
        assert is_valid_ff_condition_key("ff.invalid_key") is False
        assert is_valid_ff_condition_key("stack_id") is False
        assert is_valid_ff_condition_key("") is False

    def test_ff_condition_key_enum_values(self):
        """FFConditionKey enum should have expected values."""
        from contracts.policies.forcefield import FFConditionKey

        expected = {
            "ff.stack_id",
            "ff.lane_id",
            "ff.family_organic",
            "ff.family_inorganic",
            "ff.charge_model",
            "ff.mixing_rule",
            "ff.validation_level",
            "ff.has_inorganic",
            "ff.source_tag",
        }
        actual = {k.value for k in FFConditionKey}
        assert actual == expected


class TestBuildFFProvenanceOutput:
    """Tests for build_ff_provenance() output format."""

    def test_build_ff_provenance_output_shape(self):
        """build_ff_provenance() output should have correct structure."""
        from contracts.policies.forcefield import build_ff_provenance

        result = build_ff_provenance("bulk", "bulk_ff_gaff2", "test_source")

        # Top-level keys
        assert "metadata" in result
        assert "conditions" in result

        # Metadata structure
        assert isinstance(result["metadata"], dict)
        assert "stack_id" in result["metadata"]
        assert "lane_id" in result["metadata"]
        assert "ff_family_organic" in result["metadata"]

        # Conditions structure
        assert isinstance(result["conditions"], list)
        for cond in result["conditions"]:
            assert "condition_key" in cond
            assert "value_text" in cond
            assert "source" in cond
            assert cond["source"] == "ff_provenance"

    def test_build_ff_provenance_condition_keys_are_strings(self):
        """condition_key values should be plain strings, not enum objects."""
        from contracts.policies.forcefield import build_ff_provenance

        result = build_ff_provenance("bulk", "bulk_ff_gaff2", "test_source")

        for cond in result["conditions"]:
            key = cond["condition_key"]
            assert isinstance(key, str), f"Expected str, got {type(key)}"
            assert key.startswith("ff."), f"Key {key} should start with 'ff.'"

    def test_build_ff_provenance_bulk_study_type(self):
        """Bulk study type should set correct stack_id and lane_id."""
        from contracts.policies.forcefield import build_ff_provenance

        result = build_ff_provenance("bulk", "bulk_ff_gaff2", "test")
        meta = result["metadata"]

        assert meta["stack_id"] == "gaff2_am1bcc_v1"
        assert meta["lane_id"] == "bulk_organic"
        assert meta["ff_family_inorganic"] is None

    def test_build_ff_provenance_layer_study_type(self):
        """Layer study type should include inorganic info."""
        from contracts.policies.forcefield import build_ff_provenance

        result = build_ff_provenance("layer_bulkff", "bulk_ff_gaff2", "test")
        meta = result["metadata"]

        assert meta["stack_id"] == "gaff2_org__inorganic_profile__arith_v1"
        assert meta["lane_id"] == "dry_interface"
        assert meta["ff_family_inorganic"] == "inorganic_profile"

    def test_build_ff_provenance_nullable_key_handling(self):
        """Nullable keys (like ff.family_inorganic) should be omitted when None."""
        from contracts.policies.forcefield import build_ff_provenance

        result = build_ff_provenance("bulk", "bulk_ff_gaff2", "test")
        keys = {c["condition_key"] for c in result["conditions"]}

        # ff.family_inorganic should NOT be in conditions when None (bulk study)
        assert "ff.family_inorganic" not in keys


class TestIntegration:
    """Integration tests for FK enforcement with existing code paths."""

    def test_experiment_delete_with_conditions_via_orm(self, db_session):
        """ORM relationship cascade + DDL cascade should work together."""
        from database.models import ExperimentConditionModel, ExperimentModel

        # Setup
        exp = ExperimentModel(
            exp_id="integration_test_001",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            status="completed",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(exp)
        db_session.flush()

        # Add multiple conditions
        for i in range(5):
            cond = ExperimentConditionModel(
                experiment_id=exp.id,
                condition_key=f"test.key_{i}",
                value_type="text",
                value_text=f"value_{i}",
            )
            db_session.add(cond)
        db_session.commit()

        # Delete via ORM
        db_session.delete(exp)
        db_session.commit()

        # All conditions should be gone
        remaining = (
            db_session.query(ExperimentConditionModel)
            .filter(ExperimentConditionModel.condition_key.like("test.key_%"))
            .count()
        )
        assert remaining == 0
