"""Regression tests for god-file refactoring (v00.94.03).

Verifies that structural splits preserved import compatibility,
ORM metadata, re-export barrels, and utility function semantics.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

# ---------------------------------------------------------------------------
# Phase 0: Utility function consolidation
# ---------------------------------------------------------------------------


class TestIsoOrNone:
    """Verify iso_or_none preserves legacy _iso() behavior exactly."""

    def test_none_returns_none(self):
        from api.utils.time_utils import iso_or_none

        assert iso_or_none(None) is None

    def test_naive_datetime_no_tz_injected(self):
        """Legacy _iso() never injected UTC into naive datetimes."""
        from api.utils.time_utils import iso_or_none

        naive = datetime(2026, 3, 11, 12, 0, 0)
        result = iso_or_none(naive)
        assert result == "2026-03-11T12:00:00"
        assert "+00:00" not in result  # Must NOT inject UTC

    def test_aware_datetime_preserved(self):
        from api.utils.time_utils import iso_or_none

        aware = datetime(2026, 3, 11, 12, 0, 0, tzinfo=UTC)
        result = iso_or_none(aware)
        assert "2026-03-11T12:00:00" in result

    def test_to_utc_iso_injects_utc(self):
        """Confirm to_utc_iso() still injects UTC — distinct from iso_or_none."""
        from api.utils.time_utils import iso_or_none, to_utc_iso

        naive = datetime(2026, 3, 11, 12, 0, 0)
        assert "+00:00" in to_utc_iso(naive)
        assert "+00:00" not in iso_or_none(naive)


class TestWorkspaceUtils:
    """Verify workspace path utilities from features.common.workspace."""

    def test_resolve_workspace_path_relative(self, tmp_path, monkeypatch):
        from features.common.workspace import resolve_workspace_path

        monkeypatch.setattr("features.common.workspace.get_project_root", lambda: tmp_path)
        sub = tmp_path / "data"
        sub.mkdir()
        result = resolve_workspace_path("data")
        assert result == sub.resolve()

    def test_resolve_workspace_path_escape_blocked(self, tmp_path, monkeypatch):
        from contracts.errors import SecurityError
        from features.common.workspace import resolve_workspace_path

        monkeypatch.setattr("features.common.workspace.get_project_root", lambda: tmp_path)
        with pytest.raises(SecurityError):
            resolve_workspace_path("/etc/passwd")

    def test_as_workspace_relative_none(self):
        from features.common.workspace import as_workspace_relative

        assert as_workspace_relative(None) is None

    def test_as_workspace_relative_path(self, tmp_path, monkeypatch):
        from pathlib import Path

        from features.common.workspace import as_workspace_relative

        monkeypatch.setattr("features.common.workspace.get_project_root", lambda: tmp_path)
        result = as_workspace_relative(tmp_path / "sub" / "file.txt")
        assert result == str(Path("sub") / "file.txt")


class TestDensityUtils:
    """Verify density calculation from features.common.density."""

    def test_density_from_total_mass_basic(self):
        from features.common.density import density_from_total_mass

        # Known case: 1 mol of water (18 g/mol) in a 30x30x30 A box
        result = density_from_total_mass(18.0, (30.0, 30.0, 30.0))
        assert result is not None
        assert result > 0

    def test_density_from_total_mass_zero_volume(self):
        from features.common.density import density_from_total_mass

        assert density_from_total_mass(18.0, (0.0, 30.0, 30.0)) is None

    def test_density_from_total_mass_zero_mass(self):
        from features.common.density import density_from_total_mass

        assert density_from_total_mass(0.0, (30.0, 30.0, 30.0)) is None

    def test_total_mass_from_types(self):
        from features.common.density import total_mass_from_types

        types = [1, 2, 1]
        mass_map = {1: 12.0, 2: 16.0}
        result = total_mass_from_types(types, mass_map)
        assert result == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# Phase 1: database/models package barrel re-export
# ---------------------------------------------------------------------------


class TestModelsPackageReExport:
    """Verify all 36 model classes import from database.models barrel."""

    ALL_MODEL_NAMES = [
        "Base",
        "BinderAnalysisRunModel",
        "BinderAnalysisStudyModel",
        "MoleculeModel",
        "AdditiveCatalogModel",
        "AdditiveUsageRuleModel",
        "CrystalStructureModel",
        "AmorphousCellModel",
        "LayeredExperimentSourceModel",
        "ExperimentModel",
        "ExperimentMoleculeModel",
        "JobDependencyModel",
        "ProcessInfoModel",
        "MetricModel",
        "EIntraModel",
        "ArtifactModel",
        "PromptRegistryModel",
        "AuditLogModel",
        "LLMTurnsRawModel",
        "LLMTurnsTrainModel",
        "LiteratureCacheModel",
        "LiteratureReferenceModel",
        "LiteratureEvidenceModel",
        "LiteratureDesignLinkModel",
        "DebateSessionModel",
        "DebateRoundModel",
        "ScenarioModel",
        "SystemSettingModel",
        "PendingRecommendationModel",
        "CampaignModel",
        "CampaignWaveModel",
        "CampaignExperimentModel",
        "MLModelVersionModel",
        "PropertyDesignSessionModel",
        "DesignSimulationRecord",
    ]

    def test_all_classes_importable(self):
        """Every model class must be importable from database.models."""
        mod = importlib.import_module("database.models")
        missing = [name for name in self.ALL_MODEL_NAMES if not hasattr(mod, name)]
        assert missing == [], f"Missing re-exports: {missing}"

    def test_metadata_table_count(self):
        """ORM metadata must register all expected tables."""
        from database.models import Base

        # 37 tables = 35 (v00.99.02) + 2 (experiment contract fields from v00.99.03 DB-ML SSOT)
        #            + 1 (analysis_jobs — AnalysisJobModel restored in v01.04.00)
        #            − 1 (planning_sessions — PlanningSessionModel removed in v01.05.16)
        assert len(Base.metadata.tables) == 37

    def test_all_in___all__(self):
        """__all__ must list every model class for star-import safety."""
        from database import models

        all_list = getattr(models, "__all__", [])
        missing = [name for name in self.ALL_MODEL_NAMES if name not in all_list]
        assert missing == [], f"Missing from __all__: {missing}"

    def test_base_is_same_object(self):
        """Base from barrel and sub-module must be the same object."""
        from database.models import Base as BarrelBase
        from database.models.base import Base as DirectBase

        assert BarrelBase is DirectBase


# ---------------------------------------------------------------------------
# Phase 2a: molecule_db split
# ---------------------------------------------------------------------------


class TestMoleculeDbSplit:
    """Verify mol_types and mol_parser split preserves imports and behavior."""

    def test_mol_types_importable(self):
        from builder.mol_types import MolAtom, MolBond, MoleculeRecord, MolTopology

        assert MolAtom is not None
        assert MolBond is not None
        assert MolTopology is not None
        assert MoleculeRecord is not None

    def test_re_export_from_molecule_db(self):
        """Legacy import paths must still work."""
        from builder.mol_types import MolAtom as DirectAtom
        from builder.mol_types import MolTopology as DirectTopo
        from builder.molecule_db import MolAtom, MolTopology

        assert MolAtom is DirectAtom
        assert MolTopology is DirectTopo

    def test_mol_parser_importable(self):
        from builder.mol_parser import parse_mol_topology

        assert callable(parse_mol_topology)

    def test_mol_topology_angles(self):
        """MolTopology.get_angles() must still work after split."""
        from builder.mol_types import MolAtom, MolBond, MolTopology

        topo = MolTopology(
            mol_id="test",
            atoms=[MolAtom(i, 0, 0, 0, "C") for i in range(3)],
            bonds=[MolBond(1, 2, 1), MolBond(2, 3, 1)],
        )
        angles = topo.get_angles()
        assert len(angles) > 0
        assert all(len(a) == 3 for a in angles)


# ---------------------------------------------------------------------------
# Phase 2b: celery job types split
# ---------------------------------------------------------------------------


class TestJobTypesSplit:
    """Verify job_types extraction preserves imports."""

    def test_job_types_importable(self):
        from orchestrator.job_types import CeleryJob, CeleryJobStats, CeleryJobStatus

        assert CeleryJobStatus is not None
        assert CeleryJob is not None
        assert CeleryJobStats is not None

    def test_re_export_from_celery_job_manager(self):
        from orchestrator.celery_job_manager import CeleryJobStatus as ReExported
        from orchestrator.job_types import CeleryJobStatus as Direct

        assert ReExported is Direct

    def test_celery_job_status_values(self):
        from orchestrator.job_types import CeleryJobStatus

        assert CeleryJobStatus.PENDING == "pending"
        assert CeleryJobStatus.SUCCESS == "completed"
        assert CeleryJobStatus.FAILURE == "failed"
