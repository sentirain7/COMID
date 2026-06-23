"""Tests for ExperimentRepository conditions handling.

These tests verify the fix for UNIQUE constraint failures caused by:
1. default_factory=list causing model_dump() to always include conditions: []
2. ORM clear() + append() ordering issues causing INSERT before DELETE
"""

from contracts.schemas import ExperimentRecord
from database.models import ExperimentModel
from database.models.experiment import ExperimentConditionModel
from database.repositories.experiment_repo import ExperimentRepository


class TestExperimentRepositorySaveConditions:
    """Test save() behavior with conditions field."""

    def test_save_preserves_conditions_when_omitted(self, db_session):
        """save() with conditions not explicitly set should preserve existing conditions.

        This tests the fix for the bug where metadata-only updates would wipe
        existing conditions due to default_factory=list.
        """
        # Create experiment with condition
        exp = ExperimentModel(
            exp_id="test_preserve_001",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="pending",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(exp)
        db_session.flush()

        # Add condition directly
        cond = ExperimentConditionModel(
            experiment_id=exp.id,
            condition_key="ff.stack_id",
            value_type="text",
            value_text="gaff2_am1bcc_v1",
        )
        db_session.add(cond)
        db_session.commit()

        # Verify condition exists
        initial_count = (
            db_session.query(ExperimentConditionModel)
            .filter(ExperimentConditionModel.experiment_id == exp.id)
            .count()
        )
        assert initial_count == 1

        # Create ExperimentRecord WITHOUT setting conditions
        # (default_factory=list will create empty list, but model_fields_set won't include it)
        record = ExperimentRecord(
            exp_id="test_preserve_001",
            material_id="test_material",
            run_tier="screening",
            status="completed",  # Just updating status
            # conditions is NOT explicitly set
        )

        # Verify conditions not in model_fields_set
        assert "conditions" not in record.model_fields_set

        # Save should preserve existing conditions
        repo = ExperimentRepository(db_session)
        repo.save(record)
        db_session.commit()

        # Verify condition still exists
        final_count = (
            db_session.query(ExperimentConditionModel)
            .filter(ExperimentConditionModel.experiment_id == exp.id)
            .count()
        )
        assert final_count == 1, "Existing conditions should be preserved"

    def test_save_clears_conditions_when_explicitly_empty(self, db_session):
        """save() with conditions=[] explicitly set should clear all conditions."""
        # Create experiment with condition
        exp = ExperimentModel(
            exp_id="test_clear_001",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="pending",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(exp)
        db_session.flush()

        cond = ExperimentConditionModel(
            experiment_id=exp.id,
            condition_key="ff.stack_id",
            value_type="text",
            value_text="gaff2_am1bcc_v1",
        )
        db_session.add(cond)
        db_session.commit()

        # Create ExperimentRecord WITH explicit empty conditions
        record = ExperimentRecord(
            exp_id="test_clear_001",
            material_id="test_material",
            run_tier="screening",
            status="completed",
            conditions=[],  # Explicitly empty
        )

        # Verify conditions IS in model_fields_set
        assert "conditions" in record.model_fields_set

        # Save should clear conditions
        repo = ExperimentRepository(db_session)
        repo.save(record)
        db_session.commit()

        # Verify conditions cleared
        final_count = (
            db_session.query(ExperimentConditionModel)
            .filter(ExperimentConditionModel.experiment_id == exp.id)
            .count()
        )
        assert final_count == 0, "Conditions should be cleared when explicitly set to []"


class TestReplaceConditionsUniqueConstraint:
    """Test _replace_conditions() UNIQUE constraint handling."""

    def test_replace_conditions_same_key_no_unique_violation(self, db_session):
        """Replacing conditions with same key should not raise UNIQUE constraint error.

        This tests the fix for bulk delete + flush ordering issue.
        """
        # Create experiment with condition
        exp = ExperimentModel(
            exp_id="test_replace_001",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="pending",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(exp)
        db_session.flush()

        # Add initial condition
        cond = ExperimentConditionModel(
            experiment_id=exp.id,
            condition_key="ff.stack_id",
            value_type="text",
            value_text="old_value",
        )
        db_session.add(cond)
        db_session.commit()

        repo = ExperimentRepository(db_session)

        # Replace with same key (this SHOULD NOT raise IntegrityError)
        new_conditions = [
            {"condition_key": "ff.stack_id", "value_text": "new_value"},
        ]
        repo._replace_conditions(exp, new_conditions)
        db_session.commit()

        # Verify replacement
        result = (
            db_session.query(ExperimentConditionModel)
            .filter(ExperimentConditionModel.experiment_id == exp.id)
            .first()
        )
        assert result is not None
        assert result.value_text == "new_value"

    def test_replace_conditions_multiple_keys(self, db_session):
        """Replacing multiple conditions at once should work correctly."""
        exp = ExperimentModel(
            exp_id="test_multi_001",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="pending",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(exp)
        db_session.flush()

        # Add multiple initial conditions
        for key in ["ff.stack_id", "ff.profile", "build.seed"]:
            cond = ExperimentConditionModel(
                experiment_id=exp.id,
                condition_key=key,
                value_type="text",
                value_text=f"old_{key}",
            )
            db_session.add(cond)
        db_session.commit()

        repo = ExperimentRepository(db_session)

        # Replace all with same keys
        new_conditions = [
            {"condition_key": "ff.stack_id", "value_text": "new_stack"},
            {"condition_key": "ff.profile", "value_text": "new_profile"},
            {"condition_key": "build.seed", "value_number": 12345},
        ]
        repo._replace_conditions(exp, new_conditions)
        db_session.commit()

        # Verify all replaced
        results = (
            db_session.query(ExperimentConditionModel)
            .filter(ExperimentConditionModel.experiment_id == exp.id)
            .all()
        )
        assert len(results) == 3

        values = {r.condition_key: (r.value_text, r.value_number) for r in results}
        assert values["ff.stack_id"] == ("new_stack", None)
        assert values["ff.profile"] == ("new_profile", None)
        assert values["build.seed"] == (None, 12345)

    def test_replace_conditions_none_preserves_existing(self, db_session):
        """Passing None to _replace_conditions should preserve existing conditions."""
        exp = ExperimentModel(
            exp_id="test_none_001",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="pending",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(exp)
        db_session.flush()

        cond = ExperimentConditionModel(
            experiment_id=exp.id,
            condition_key="ff.stack_id",
            value_type="text",
            value_text="should_stay",
        )
        db_session.add(cond)
        db_session.commit()

        repo = ExperimentRepository(db_session)

        # Pass None
        repo._replace_conditions(exp, None)
        db_session.commit()

        # Verify preserved
        count = (
            db_session.query(ExperimentConditionModel)
            .filter(ExperimentConditionModel.experiment_id == exp.id)
            .count()
        )
        assert count == 1


class TestDeleteWithExplicitChildCleanup:
    """Test delete() with explicit child row cleanup."""

    def test_delete_clears_conditions(self, db_session):
        """delete() should explicitly remove experiment_conditions."""
        exp = ExperimentModel(
            exp_id="test_delete_001",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="pending",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
        )
        db_session.add(exp)
        db_session.flush()

        cond = ExperimentConditionModel(
            experiment_id=exp.id,
            condition_key="ff.stack_id",
            value_type="text",
            value_text="test",
        )
        db_session.add(cond)
        db_session.commit()

        experiment_id = exp.id

        repo = ExperimentRepository(db_session)
        result = repo.delete("test_delete_001")
        db_session.commit()

        assert result is True

        # Verify experiment deleted
        assert (
            db_session.query(ExperimentModel)
            .filter(ExperimentModel.exp_id == "test_delete_001")
            .first()
            is None
        )

        # Verify conditions deleted (explicit cleanup, not relying on FK cascade)
        cond_count = (
            db_session.query(ExperimentConditionModel)
            .filter(ExperimentConditionModel.experiment_id == experiment_id)
            .count()
        )
        assert cond_count == 0, "Conditions should be explicitly deleted"
