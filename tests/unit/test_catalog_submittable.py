"""Test catalog artifact readiness signalling.

v00.99.96 policy (strict fail-closed at preview):
1. Organic curated route + missing artifact → is_submittable=False,
   blocked_reason set, artifact_warning set (display compat).
2. Organic curated route + incomplete artifact → is_submittable=False,
   blocked_reason set, artifact_warning set.
3. Organic curated route + complete artifact → is_submittable=True,
   blocked_reason None, artifact_warning None.

This replaces the v00.99.30 fail-open policy because build-time
auto-regeneration via ensure_organic_artifact was removed — FF
generation now happens only in the canonical Molecules catalog.
Preview/validate is the only gate.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


class TestOrganicArtifactReadiness:
    """_get_organic_artifact_readiness() primitive."""

    def test_missing_artifact_reported_as_incomplete(self, tmp_path):
        from features.molecules.catalog import _get_organic_artifact_readiness

        missing_path = tmp_path / "Missing.json"
        with patch(
            "features.molecules.artifact_service.get_artifact_path",
            return_value=missing_path,
        ):
            result = _get_organic_artifact_readiness("TestMol", None)

        assert result["exists"] is False
        assert result["complete"] is False
        assert result["blocked_reason"] is not None
        assert "not found" in result["blocked_reason"].lower()

    def test_incomplete_artifact_reported_as_incomplete(self, tmp_path):
        from features.molecules.catalog import _get_organic_artifact_readiness

        incomplete = {
            "schema_version": 2,
            "ff_family": "organic_gaff2",
            "mol_id": "TestMol",
            "atoms": [
                {"index": 1, "element": "C", "ff_type": "c3", "charge": 0.0},
            ],
            "bond_types": [],
        }
        artifact_path = tmp_path / "TestMol.json"
        artifact_path.write_text(json.dumps(incomplete))

        with patch(
            "features.molecules.artifact_service.get_artifact_path",
            return_value=artifact_path,
        ):
            result = _get_organic_artifact_readiness("TestMol", None)

        assert result["exists"] is True
        assert result["complete"] is False
        assert "incomplete" in (result["blocked_reason"] or "").lower()

    def test_complete_artifact_reported_as_complete(self, tmp_path):
        from features.molecules.catalog import _get_organic_artifact_readiness

        complete = {
            "schema_version": 2,
            "ff_family": "organic_gaff2",
            "mol_id": "TestMol",
            "formal_charge": 0,
            "charge_sum": 0.0,
            "atoms": [
                {
                    "index": 1,
                    "element": "C",
                    "ff_type": "c3",
                    "charge": 0.0,
                    "epsilon": 0.1094,
                    "sigma": 3.3997,
                },
            ],
            "bond_types": [{"type": 1, "k": 300.0, "r0": 1.5}],
            "angle_types": [],
        }
        artifact_path = tmp_path / "TestMol.json"
        artifact_path.write_text(json.dumps(complete))

        with patch(
            "features.molecules.artifact_service.get_artifact_path",
            return_value=artifact_path,
        ):
            result = _get_organic_artifact_readiness("TestMol", None)

        assert result["exists"] is True
        assert result["complete"] is True
        assert result["blocked_reason"] is None


class TestResolveFFHintOrganicCuratedFailOpen:
    """resolve_ff_hint() organic_curated_artifact route — v00.99.96 strict.

    Class name kept for git-history continuity; the semantic is now
    fail-closed (missing/incomplete artifact blocks submit).
    """

    def _mock_db(self, ff_assignment):
        db = MagicMock()
        db.get_additive_definition.return_value = None
        db.get_additives_load_error.return_value = None
        db.get_ff_assignment.return_value = ff_assignment
        db.get_ff_assignment_load_error.return_value = None
        return db

    def test_missing_artifact_is_submittable_with_warning(self):
        """v00.99.96: missing artifact blocks submit (was warning-only)."""
        from features.molecules.catalog import resolve_ff_hint

        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "TestMol",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        db = self._mock_db(ff_assignment)

        with (
            patch("api.deps.get_molecule_db", return_value=db),
            patch(
                "features.molecules.catalog._get_organic_artifact_readiness",
                return_value={
                    "exists": False,
                    "complete": False,
                    "source_id": "TestMol",
                    "blocked_reason": "Artifact not found for 'TestMol'.",
                },
            ),
        ):
            result = resolve_ff_hint("TestMol")

        # v00.99.96 strict: missing artifact blocks submit; build path no
        # longer auto-regenerates. Operator must generate via the canonical
        # Molecules catalog.
        assert result["is_submittable"] is False
        assert result["blocked_reason"] is not None
        assert "Generate" in result["blocked_reason"]
        assert "Molecules catalog" in result["blocked_reason"]
        assert result["artifact_warning"] is not None
        assert "not found" in result["artifact_warning"].lower()
        assert result["ff_display_label"] == "GAFF2 (not generated)"
        assert result["route"] == "organic_curated_artifact"
        assert result["status"] == "active"
        assert result["ff_hint"] == "gaff2"

    def test_incomplete_artifact_is_submittable_with_warning(self):
        """v00.99.96: incomplete artifact blocks submit (was warning-only)."""
        from features.molecules.catalog import resolve_ff_hint

        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "TestMol",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        db = self._mock_db(ff_assignment)

        with (
            patch("api.deps.get_molecule_db", return_value=db),
            patch(
                "features.molecules.catalog._get_organic_artifact_readiness",
                return_value={
                    "exists": True,
                    "complete": False,
                    "source_id": "TestMol",
                    "blocked_reason": "Artifact incomplete for 'TestMol' (missing LJ params).",
                },
            ),
        ):
            result = resolve_ff_hint("TestMol")

        # v00.99.96 strict: incomplete artifact also blocks submit.
        assert result["is_submittable"] is False
        assert "Generate" in (result["blocked_reason"] or "")
        assert "incomplete" in (result["artifact_warning"] or "").lower()
        assert result["ff_display_label"] == "GAFF2 (not generated)"

    def test_complete_artifact_is_submittable_without_warning(self):
        from features.molecules.catalog import resolve_ff_hint

        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "TestMol",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        db = self._mock_db(ff_assignment)

        with (
            patch("api.deps.get_molecule_db", return_value=db),
            patch(
                "features.molecules.catalog._get_organic_artifact_readiness",
                return_value={
                    "exists": True,
                    "complete": True,
                    "source_id": "TestMol",
                    "blocked_reason": None,
                },
            ),
        ):
            result = resolve_ff_hint("TestMol")

        assert result["is_submittable"] is True
        assert result["blocked_reason"] is None
        assert result["artifact_warning"] is None
        assert result["ff_display_label"] == "GAFF2"

    def test_missing_status_is_backfilled_from_router_decision(self):
        """Explicit organic route with no status → router decision backfills it."""
        from features.molecules.catalog import resolve_ff_hint
        from forcefield.typing_router import TypingRouterDecision, TypingStrategy

        ff_assignment = {
            "route": "organic_curated_artifact",
            # status intentionally omitted
            "source_id": "TestMol",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        db = self._mock_db(ff_assignment)
        fake_decision = TypingRouterDecision(
            strategy=TypingStrategy.ORGANIC_CURATED_ARTIFACT,
            source_id="TestMol",
            status="active",
        )
        with (
            patch("api.deps.get_molecule_db", return_value=db),
            patch(
                "forcefield.typing_router.resolve_typing_strategy",
                return_value=fake_decision,
            ),
            patch(
                "features.molecules.catalog._get_organic_artifact_readiness",
                return_value={
                    "exists": True,
                    "complete": True,
                    "source_id": "TestMol",
                    "blocked_reason": None,
                },
            ),
        ):
            result = resolve_ff_hint("TestMol")
        assert result["route"] == "organic_curated_artifact"
        assert result["status"] == "active"


class TestSourceIdResolution:
    """Source_id resolution in artifact readiness."""

    def test_variant_sentinel_resolution(self, tmp_path):
        from features.molecules.catalog import _get_organic_artifact_readiness

        ff_assignment = {"source_id": "_variant_"}
        missing_path = tmp_path / "U-SA-Squalane.json"

        with patch(
            "features.molecules.artifact_service.get_artifact_path",
            return_value=missing_path,
        ):
            result = _get_organic_artifact_readiness("U-SA-Squalane", ff_assignment)

        # source_id should resolve to mol_id, not "_variant_"
        assert result["source_id"] == "U-SA-Squalane"

    def test_explicit_source_id_used(self, tmp_path):
        from features.molecules.catalog import _get_organic_artifact_readiness

        ff_assignment = {"source_id": "SharedArtifact"}
        missing_path = tmp_path / "SharedArtifact.json"

        with patch(
            "features.molecules.artifact_service.get_artifact_path",
            return_value=missing_path,
        ):
            result = _get_organic_artifact_readiness("MyMolecule", ff_assignment)

        assert result["source_id"] == "SharedArtifact"


class TestResolveFFHintReturnShape:
    """Every resolve_ff_hint() return path must include the same keys."""

    REQUIRED_KEYS = frozenset(
        [
            "ff_hint",
            "ff_display_label",
            "parameterization_mode",
            "submit_ff_type",
            "is_submittable",
            "blocked_reason",
            "route",
            "status",
            "artifact_warning",
        ]
    )

    def _assert_shape(self, result: dict) -> None:
        missing = self.REQUIRED_KEYS - set(result)
        assert not missing, f"resolve_ff_hint missing keys: {missing}"

    def test_happy_path_includes_artifact_warning_key(self):
        from features.molecules.catalog import resolve_ff_hint

        db = MagicMock()
        db.get_additive_definition.return_value = None
        db.get_additives_load_error.return_value = None
        db.get_ff_assignment.return_value = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "TestMol",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        db.get_ff_assignment_load_error.return_value = None

        with (
            patch("api.deps.get_molecule_db", return_value=db),
            patch(
                "features.molecules.catalog._get_organic_artifact_readiness",
                return_value={
                    "exists": True,
                    "complete": True,
                    "source_id": "TestMol",
                    "blocked_reason": None,
                },
            ),
        ):
            result = resolve_ff_hint("TestMol")
        self._assert_shape(result)

    def test_authoring_error_includes_artifact_warning_key(self):
        from features.molecules.catalog import resolve_ff_hint

        with patch("api.deps.get_molecule_db") as mock_db:
            mock_db.return_value.get_additive_definition.return_value = None
            mock_db.return_value.get_additives_load_error.return_value = None
            mock_db.return_value.get_ff_assignment.return_value = None
            mock_db.return_value.get_ff_assignment_load_error.return_value = None
            result = resolve_ff_hint("UnknownMolecule")
        self._assert_shape(result)

    def test_exception_path_includes_artifact_warning_key(self):
        from features.molecules.catalog import resolve_ff_hint

        db = MagicMock()
        db.get_additive_definition.side_effect = RuntimeError("boom")
        with patch("api.deps.get_molecule_db", return_value=db):
            result = resolve_ff_hint("anything")
        self._assert_shape(result)
        assert result["artifact_warning"] is None
        assert result["is_submittable"] is False
