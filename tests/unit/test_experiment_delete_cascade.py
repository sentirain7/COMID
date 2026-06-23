"""Unit tests for experiment deletion cascade logic.

Tests verify that deleting an experiment properly:
1. Deletes direct outputs (metrics, e_intra, campaign_experiments)
2. Detaches workflow references (SET NULL for amorphous_cells, audit_log, etc.)
3. Cleans up JSON array references
4. Handles artifact ref_count correctly (aggregated decrement)
5. Preserves terminal recommendation status while clearing active ones
"""

import pytest


class TestExperimentDeleteCascade:
    """Experiment delete cascade verification tests."""

    def _create_experiment(self, db_session, exp_id: str, status: str = "completed"):
        """Create a test experiment."""
        from database.models import ExperimentModel

        exp = ExperimentModel(
            exp_id=exp_id,
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status=status,
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            composition_error_l1=0.01,
            target_atoms=100000,
            actual_atoms=99850,
            seed=42,
            topology_hash="topo0001",
            protocol_hash="prot0001",
            temperature_K=298.0,
            pressure_atm=1.0,
        )
        db_session.add(exp)
        db_session.flush()
        return exp

    def test_delete_removes_e_intra(self, db_session):
        """E_intra rows with source_exp_id should be deleted."""
        from database.models.metric import EIntraModel
        from features.experiments.experiment_lifecycle import _delete_one

        exp = self._create_experiment(db_session, "exp-e-intra-test")
        e_intra = EIntraModel(
            mol_id="test-mol",
            ff_name="GAFF2",
            ff_version="2.2",
            temperature_K=298.0,
            e_intra=0.0,
            source_exp_id=exp.exp_id,
        )
        db_session.add(e_intra)
        db_session.commit()

        result = _delete_one(db_session, exp.exp_id)
        db_session.commit()

        assert result["success"]
        count = (
            db_session.query(EIntraModel).filter(EIntraModel.source_exp_id == exp.exp_id).count()
        )
        assert count == 0

    def test_delete_aggregates_artifact_refcount(self, db_session):
        """Multiple metrics sharing same artifact should decrement ref_count correctly."""
        from database.models import MetricModel
        from database.models.metric import MetricArrayArtifactModel
        from features.experiments.experiment_lifecycle import _delete_one

        # Create artifact with ref_count=5 (shared by 5 experiments, 3 metrics each)
        artifact = MetricArrayArtifactModel(
            content_hash="shared-artifact-hash",
            storage_path="/nonexistent/path.parquet",
            ref_count=5,
        )
        db_session.add(artifact)
        db_session.flush()

        exp = self._create_experiment(db_session, "exp-refcount-test")

        # Create 3 metrics all referencing the same artifact
        for i in range(3):
            metric = MetricModel(
                exp_id=exp.exp_id,
                experiment_id=exp.id,
                metric_name=f"test_metric_{i}",
                namespace="bulk_ff",
                unit="test",
                value=1.0,
                array_artifact_id=artifact.id,
            )
            db_session.add(metric)
        db_session.commit()

        artifact_id = artifact.id
        _delete_one(db_session, exp.exp_id)
        db_session.commit()

        # Artifact should still exist with ref_count = 5 - 3 = 2
        artifact_after = db_session.get(MetricArrayArtifactModel, artifact_id)
        assert artifact_after is not None
        assert artifact_after.ref_count == 2

    def test_delete_removes_artifact_when_refcount_zero(self, db_session):
        """Artifact should be deleted when ref_count reaches 0."""
        from database.models import MetricModel
        from database.models.metric import MetricArrayArtifactModel
        from features.experiments.experiment_lifecycle import _delete_one

        # Create artifact with ref_count=1
        artifact = MetricArrayArtifactModel(
            content_hash="single-use-artifact",
            storage_path="/nonexistent/single.parquet",
            ref_count=1,
        )
        db_session.add(artifact)
        db_session.flush()

        exp = self._create_experiment(db_session, "exp-artifact-delete-test")
        metric = MetricModel(
            exp_id=exp.exp_id,
            experiment_id=exp.id,
            metric_name="test_metric",
            namespace="bulk_ff",
            unit="test",
            value=1.0,
            array_artifact_id=artifact.id,
        )
        db_session.add(metric)
        db_session.commit()

        artifact_id = artifact.id
        _delete_one(db_session, exp.exp_id)
        db_session.commit()

        # Artifact should be deleted
        assert db_session.get(MetricArrayArtifactModel, artifact_id) is None

    def test_delete_defers_artifact_file_unlink_until_after_commit(
        self, db_session, tmp_path, monkeypatch
    ):
        """Artifact files should not be unlinked inside the DB transaction."""
        import features.common.workspace as workspace_module
        from database.models import MetricModel
        from database.models.metric import MetricArrayArtifactModel
        from features.experiments.experiment_lifecycle import (
            _delete_deferred_files,
            _delete_one,
        )

        artifact_file = tmp_path / "array.parquet"
        artifact_file.write_text("array-data")

        artifact = MetricArrayArtifactModel(
            content_hash="deferred-delete-artifact",
            storage_path=str(artifact_file),
            ref_count=1,
        )
        db_session.add(artifact)
        db_session.flush()

        exp = self._create_experiment(db_session, "exp-deferred-file-delete")
        db_session.add(
            MetricModel(
                exp_id=exp.exp_id,
                experiment_id=exp.id,
                metric_name="rdf_curve",
                namespace="bulk_ff",
                unit="a.u.",
                value=None,
                array_artifact_id=artifact.id,
            )
        )
        db_session.commit()

        result = _delete_one(db_session, exp.exp_id)

        assert result["success"]
        assert str(artifact_file) in result["deferred_files"]
        assert artifact_file.exists()

        db_session.commit()
        assert artifact_file.exists()

        monkeypatch.setattr(workspace_module, "resolve_workspace_path", lambda value: artifact_file)
        _delete_deferred_files(result["deferred_files"])
        assert not artifact_file.exists()

    def test_delete_sets_null_on_audit_log(self, db_session):
        """AuditLog row should be preserved but exp_id set to NULL."""
        from database.models.llm import AuditLogModel
        from features.experiments.experiment_lifecycle import _delete_one

        exp = self._create_experiment(db_session, "exp-audit-test")
        audit = AuditLogModel(
            session_id="test-session",
            action_type="test_action",
            actor="system",
            exp_id=exp.exp_id,
        )
        db_session.add(audit)
        db_session.commit()

        audit_id = audit.id
        _delete_one(db_session, exp.exp_id)
        db_session.commit()

        audit_after = db_session.get(AuditLogModel, audit_id)
        assert audit_after is not None  # Row preserved
        assert audit_after.exp_id is None  # Reference cleared

    def test_delete_cancels_active_recommendation_only(self, db_session):
        """Active recommendations should be cancelled; terminal status preserved."""
        from database.models.recommendation import PendingRecommendationModel
        from features.experiments.experiment_lifecycle import _delete_one

        exp = self._create_experiment(db_session, "exp-rec-test")

        # Active status recommendation
        active_rec = PendingRecommendationModel(
            id="prec-active-test",
            source="test",
            status="queued",  # Active status
            queued_exp_id=exp.exp_id,
        )
        # Terminal status recommendation
        terminal_rec = PendingRecommendationModel(
            id="prec-terminal-test",
            source="test",
            status="completed",  # Terminal status
            queued_exp_id=exp.exp_id,
        )
        db_session.add_all([active_rec, terminal_rec])
        db_session.commit()

        _delete_one(db_session, exp.exp_id)
        db_session.commit()

        active_after = db_session.get(PendingRecommendationModel, "prec-active-test")
        terminal_after = db_session.get(PendingRecommendationModel, "prec-terminal-test")

        # Active → cancelled
        assert active_after.status == "cancelled"
        assert active_after.queued_exp_id is None

        # Terminal status preserved
        assert terminal_after.status == "completed"
        assert terminal_after.queued_exp_id is None

    def test_delete_removes_exp_from_json_array(self, db_session):
        """Exp_id should be removed from simulation_exp_ids_json array."""
        from database.models.recommendation import PropertyDesignSessionModel
        from features.experiments.experiment_lifecycle import _delete_one

        exp = self._create_experiment(db_session, "exp-json-test")
        design_session = PropertyDesignSessionModel(
            id="design-json-test",
            state="intake",
            flow_type="property_design",
            simulation_exp_ids_json=[exp.exp_id, "other-exp-1", "other-exp-2"],
        )
        db_session.add(design_session)
        db_session.commit()

        _delete_one(db_session, exp.exp_id)
        db_session.commit()

        session_after = db_session.get(PropertyDesignSessionModel, "design-json-test")
        assert exp.exp_id not in session_after.simulation_exp_ids_json
        assert "other-exp-1" in session_after.simulation_exp_ids_json
        assert "other-exp-2" in session_after.simulation_exp_ids_json

    def test_delete_removes_exp_from_nested_json(self, db_session):
        """Exp_id in nested dict structure (source_records_json) should be removed."""
        from database.models.recommendation import PendingRecommendationModel
        from features.experiments.experiment_lifecycle import _delete_one

        exp = self._create_experiment(db_session, "exp-nested-json-test")
        rec = PendingRecommendationModel(
            id="prec-nested-test",
            source="test",
            status="pending",
            source_records_json=[
                {"exp_id": exp.exp_id, "metric": "density", "value": 1.0},
                {"exp_id": "other-exp", "metric": "ced", "value": 2.0},
            ],
        )
        db_session.add(rec)
        db_session.commit()

        _delete_one(db_session, exp.exp_id)
        db_session.commit()

        rec_after = db_session.get(PendingRecommendationModel, "prec-nested-test")
        assert len(rec_after.source_records_json) == 1
        assert rec_after.source_records_json[0]["exp_id"] == "other-exp"

    def test_delete_sets_null_on_amorphous_cell(self, db_session):
        """AmorphousCell.stabilization_exp_id should be set to NULL."""
        from database.models.structure import AmorphousCellModel
        from features.experiments.experiment_lifecycle import _delete_one

        exp = self._create_experiment(db_session, "exp-amorphous-test")
        cell = AmorphousCellModel(
            amorphous_id="cell-test",
            name="Test Cell",
            status="ready",
            stabilization_exp_id=exp.exp_id,
        )
        db_session.add(cell)
        db_session.commit()

        _delete_one(db_session, exp.exp_id)
        db_session.commit()

        cell_after = (
            db_session.query(AmorphousCellModel)
            .filter(AmorphousCellModel.amorphous_id == "cell-test")
            .first()
        )
        assert cell_after is not None  # Row preserved
        assert cell_after.stabilization_exp_id is None  # Reference cleared

    def test_delete_rejects_non_deletable_status(self, db_session):
        """Experiments with non-deletable status should be rejected."""
        from features.experiments.experiment_lifecycle import _delete_one

        exp = self._create_experiment(db_session, "exp-running-test", status="running")
        db_session.commit()

        result = _delete_one(db_session, exp.exp_id)

        assert result["success"] is False
        assert "status:running" in result.get("reason", "")

    def test_delete_removes_campaign_experiments(self, db_session):
        """CampaignExperiment linkages should be deleted."""
        from database.models.campaign import (
            CampaignExperimentModel,
            CampaignModel,
            CampaignWaveModel,
        )
        from features.experiments.experiment_lifecycle import _delete_one

        # Create campaign hierarchy
        campaign = CampaignModel(id="campaign-test", name="Test Campaign", status="draft")
        db_session.add(campaign)
        db_session.flush()

        wave = CampaignWaveModel(campaign_id=campaign.id, wave_no=1, status="draft")
        db_session.add(wave)
        db_session.flush()

        exp = self._create_experiment(db_session, "exp-campaign-test")
        camp_exp = CampaignExperimentModel(
            wave_id=wave.id,
            exp_id=exp.exp_id,
            submission_status="pending",
        )
        db_session.add(camp_exp)
        db_session.commit()

        _delete_one(db_session, exp.exp_id)
        db_session.commit()

        count = (
            db_session.query(CampaignExperimentModel)
            .filter(CampaignExperimentModel.exp_id == exp.exp_id)
            .count()
        )
        assert count == 0

    def test_delete_sets_design_simulation_record_cancelled(self, db_session):
        """DesignSimulationRecord should have exp_id=NULL and status='cancelled'."""
        from database.models.recommendation import (
            DesignSimulationRecord,
            PropertyDesignSessionModel,
        )
        from features.experiments.experiment_lifecycle import _delete_one

        # Create design session first
        design_session = PropertyDesignSessionModel(
            id="design-sim-test",
            state="simulating",
            flow_type="property_design",
        )
        db_session.add(design_session)
        db_session.flush()

        exp = self._create_experiment(db_session, "exp-design-sim-test")
        record = DesignSimulationRecord(
            design_session_id=design_session.id,
            idempotency_key="test-key",
            exp_id=exp.exp_id,
            status="queued",
        )
        db_session.add(record)
        db_session.commit()

        record_id = record.id
        _delete_one(db_session, exp.exp_id)
        db_session.commit()

        record_after = db_session.get(DesignSimulationRecord, record_id)
        assert record_after is not None  # Row preserved
        assert record_after.exp_id is None  # Reference cleared
        assert record_after.status == "cancelled"  # Status updated


class TestBatchDeletePartialSuccess:
    """Test batch deletion with partial success."""

    def test_batch_delete_continues_on_failure(self, db_session):
        """One experiment deletion failure should not block others."""
        import asyncio

        from database.models import ExperimentModel
        from features.experiments.experiment_lifecycle import batch_delete_experiments

        # Create experiments with different statuses
        exp1 = ExperimentModel(
            exp_id="batch-exp-1",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="completed",  # Deletable
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            composition_error_l1=0.01,
            target_atoms=100000,
            actual_atoms=99850,
            seed=42,
            topology_hash="topo1",
            protocol_hash="prot1",
            temperature_K=298.0,
            pressure_atm=1.0,
        )
        exp2 = ExperimentModel(
            exp_id="batch-exp-2",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="running",  # NOT deletable
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            composition_error_l1=0.01,
            target_atoms=100000,
            actual_atoms=99850,
            seed=43,
            topology_hash="topo2",
            protocol_hash="prot2",
            temperature_K=298.0,
            pressure_atm=1.0,
        )
        exp3 = ExperimentModel(
            exp_id="batch-exp-3",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="failed",  # Deletable
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            composition_error_l1=0.01,
            target_atoms=100000,
            actual_atoms=99850,
            seed=44,
            topology_hash="topo3",
            protocol_hash="prot3",
            temperature_K=298.0,
            pressure_atm=1.0,
        )
        db_session.add_all([exp1, exp2, exp3])
        db_session.commit()

        results = asyncio.run(
            batch_delete_experiments(["batch-exp-1", "batch-exp-2", "batch-exp-3"])
        )

        assert results["total"] == 3
        assert results["succeeded"] == 2  # exp1, exp3
        assert results["skipped"] == 1  # exp2 (running)


class TestDeleteFailureRollback:
    """Test that DB cascade failures properly rollback the transaction."""

    def _create_experiment(self, db_session, exp_id: str, status: str = "completed"):
        """Create a test experiment."""
        from database.models import ExperimentModel

        exp = ExperimentModel(
            exp_id=exp_id,
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status=status,
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            composition_error_l1=0.01,
            target_atoms=100000,
            actual_atoms=99850,
            seed=42,
            topology_hash="topo_rollback",
            protocol_hash="prot_rollback",
            temperature_K=298.0,
            pressure_atm=1.0,
        )
        db_session.add(exp)
        db_session.flush()
        return exp

    def test_db_cascade_failure_prevents_experiment_deletion(self, db_session, monkeypatch):
        """If DB cascade fails, experiment row should NOT be deleted (rollback)."""
        import features.experiments.experiment_lifecycle as lifecycle_module
        from database.models import ExperimentModel
        from database.models.metric import EIntraModel
        from features.experiments.experiment_lifecycle import _delete_one

        exp = self._create_experiment(db_session, "exp-rollback-test")

        # Add e_intra entry
        e_intra = EIntraModel(
            mol_id="test-mol",
            ff_name="GAFF2",
            ff_version="2.2",
            temperature_K=298.0,
            e_intra=0.0,
            source_exp_id=exp.exp_id,
        )
        db_session.add(e_intra)
        db_session.commit()

        # Mock _delete_direct_outputs to raise an exception
        def raise_error(*args, **kwargs):
            raise Exception("Simulated DB error")

        monkeypatch.setattr(lifecycle_module, "_delete_direct_outputs", raise_error)

        # Attempt deletion — should raise and NOT delete experiment
        with pytest.raises(Exception, match="Simulated DB error"):
            _delete_one(db_session, exp.exp_id)

        # Rollback the failed transaction
        db_session.rollback()

        # Experiment should still exist
        exp_after = (
            db_session.query(ExperimentModel)
            .filter(ExperimentModel.exp_id == "exp-rollback-test")
            .first()
        )
        assert exp_after is not None, "Experiment should NOT be deleted on cascade failure"

        # e_intra should also still exist (not orphaned)
        e_intra_after = (
            db_session.query(EIntraModel).filter(EIntraModel.source_exp_id == exp.exp_id).first()
        )
        assert e_intra_after is not None, "E_intra should NOT be orphaned"

    def test_metrics_cascade_failure_prevents_experiment_deletion(self, db_session, monkeypatch):
        """If metrics deletion fails, experiment should NOT be deleted."""
        import features.experiments.experiment_lifecycle as lifecycle_module
        from database.models import ExperimentModel, MetricModel
        from features.experiments.experiment_lifecycle import _delete_one

        exp = self._create_experiment(db_session, "exp-metrics-rollback")

        # Add a metric
        metric = MetricModel(
            exp_id=exp.exp_id,
            experiment_id=exp.id,
            metric_name="density",
            namespace="bulk_ff",
            unit="g/cm3",
            value=1.0,
        )
        db_session.add(metric)
        db_session.commit()

        # Mock _delete_metrics_with_artifacts to raise
        def raise_error(*args, **kwargs):
            raise Exception("Metrics deletion failed")

        monkeypatch.setattr(lifecycle_module, "_delete_metrics_with_artifacts", raise_error)

        with pytest.raises(Exception, match="Metrics deletion failed"):
            _delete_one(db_session, exp.exp_id)

        db_session.rollback()

        # Both experiment and metric should still exist
        assert (
            db_session.query(ExperimentModel)
            .filter(ExperimentModel.exp_id == "exp-metrics-rollback")
            .first()
            is not None
        )

        assert (
            db_session.query(MetricModel)
            .filter(MetricModel.exp_id == "exp-metrics-rollback")
            .first()
            is not None
        )
