"""Phase 9: Single Molecule FF resolver regression tests.

Tests cover the SSOT FF resolver in features.molecules.catalog.resolve_ff_hint(),
which mirrors the fail-closed validation in StructureBuilder.

Test scope:
- SARA / single_moles molecules → always submittable, GAFF2
- Organic additives → submittable, GAFF2
- Inorganic additives with valid profile → submittable, INTERFACE
- Blocked placeholder additives → NOT submittable
- Inorganic without mode → NOT submittable
- YAML load error scoping (additives only)
- Default fail-safe on exceptions
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from features.molecules.catalog import resolve_ff_hint  # noqa: E402


def _patch_db(additive_def, yaml_err=None, ff_assignment=None, ff_err=None):
    """Helper: patch get_molecule_db with a configurable mock.

    Wave 0 adds ``ff_assignment`` and ``ff_err`` so tests can exercise the
    ff_assignment SSOT path without accidentally returning ``MagicMock``
    sentinels from unconfigured attributes (which would be truthy and break
    the router's ``is not None`` checks).
    """
    mock_db = MagicMock()
    mock_db.get_additive_definition.return_value = additive_def
    mock_db.get_additives_load_error.return_value = yaml_err
    mock_db.get_ff_assignment.return_value = ff_assignment
    mock_db.get_ff_assignment_load_error.return_value = ff_err
    return patch("api.deps.get_molecule_db", return_value=mock_db)


def _patch_readiness_complete():
    """Patch readiness helper to report a fully curated artifact."""
    return patch(
        "features.molecules.catalog._get_organic_artifact_readiness",
        return_value={
            "exists": True,
            "complete": True,
            "source_id": "patched",
            "blocked_reason": None,
        },
    )


def _patch_readiness_missing():
    """Patch readiness helper to report a missing artifact."""
    return patch(
        "features.molecules.catalog._get_organic_artifact_readiness",
        return_value={
            "exists": False,
            "complete": False,
            "source_id": "patched",
            "blocked_reason": "Artifact not found for 'patched'.",
        },
    )


class TestResolveFFHintNonAdditive:
    """SARA and single_moles molecules with ff_assignment."""

    def test_sara_molecule_with_curated_artifact(self):
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "Thio_v1.json",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        with _patch_db(additive_def=None, ff_assignment=ff_assignment), _patch_readiness_complete():
            result = resolve_ff_hint("U-AS-Thio-0293")
        assert result["ff_hint"] == "gaff2"
        assert result["submit_ff_type"] == "bulk_ff_gaff2"
        assert result["is_submittable"] is True
        assert result["blocked_reason"] is None
        assert result["artifact_warning"] is None

    def test_sara_molecule_missing_artifact_still_submittable(self):
        """v00.99.96 fail-closed: missing artifact blocks submit (was warning)."""
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "_variant_",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        with _patch_db(additive_def=None, ff_assignment=ff_assignment), _patch_readiness_missing():
            result = resolve_ff_hint("U-AS-Thio-0293")
        # v00.99.96 strict: build path is observe-only so preview must
        # block submit when the artifact is not on disk.
        assert result["is_submittable"] is False
        assert "Generate" in (result["blocked_reason"] or "")
        assert result["artifact_warning"] is not None
        assert "not found" in result["artifact_warning"].lower()
        assert result["ff_display_label"] == "GAFF2 (not generated)"

    def test_single_moles_with_curated_artifact(self):
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "Thiophenol_v1.json",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        with _patch_db(additive_def=None, ff_assignment=ff_assignment), _patch_readiness_complete():
            result = resolve_ff_hint("Thiophenol")
        assert result["is_submittable"] is True
        assert result["artifact_warning"] is None

    def test_no_ff_assignment_blocks_molecule(self):
        """Phase 6: molecules without ff_assignment are BLOCKED."""
        with _patch_db(additive_def=None):
            result = resolve_ff_hint("U-AR-Phen-0293")
        assert result["is_submittable"] is False
        assert result["blocked_reason"] is not None
        # Authoring-error path still exposes the artifact_warning key.
        assert "artifact_warning" in result


class TestResolveFFHintOrganicAdditive:
    """Organic additives — submittable with curated artifact."""

    def test_organic_additive_with_ff_assignment(self):
        """Organic additives with proper ff_assignment are submittable."""
        additive_def = {"category": "organic_polymer", "name": "SBS"}
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "SBS_v1.json",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        with (
            _patch_db(additive_def=additive_def, ff_assignment=ff_assignment),
            _patch_readiness_complete(),
        ):
            result = resolve_ff_hint("SBS")
        assert result["is_submittable"] is True

    def test_organic_additive_missing_artifact_warns_not_blocks(self):
        """v00.99.96 fail-closed: additive with missing artifact blocks submit.

        Legacy name retained; the semantic flipped when the build path
        stopped auto-regenerating via ensure_organic_artifact.
        """
        additive_def = {"category": "organic_polymer", "name": "Lignin"}
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "Lignin",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        with (
            _patch_db(additive_def=additive_def, ff_assignment=ff_assignment),
            _patch_readiness_missing(),
        ):
            result = resolve_ff_hint("Lignin")
        assert result["is_submittable"] is False
        assert "Generate" in (result["blocked_reason"] or "")
        assert result["artifact_warning"] is not None

    def test_organic_additive_no_ff_assignment_blocked(self):
        """Phase 6: organic additives without ff_assignment are BLOCKED."""
        additive_def = {
            "category": "carbon",
            "parameterization": {"mode": "organic_gaff2_passthrough"},
        }
        with _patch_db(additive_def=additive_def):
            result = resolve_ff_hint("Carbon_Nano_Tube")
        assert result["is_submittable"] is False


class TestResolveFFHintInorganicAdditive:
    """Inorganic additives — INTERFACE FF profile."""

    def test_inorganic_profile_submittable(self):
        additive_def = {
            "category": "inorganic",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "silica_hydroxylated_v1",
            },
        }
        with _patch_db(additive_def=additive_def):
            result = resolve_ff_hint("SiO2")
        assert result["ff_hint"] == "interface_profile"
        assert result["ff_display_label"] == "INTERFACE-derived inorganic"
        assert result["submit_ff_type"] == "bulk_ff_gaff2"
        assert result["is_submittable"] is True
        assert result["parameterization_mode"] == "inorganic_profile"

    def test_inorganic_without_mode_blocked(self):
        """Inorganic additive missing parameterization.mode → fail-closed."""
        additive_def = {"category": "inorganic", "parameterization": {}}
        with _patch_db(additive_def=additive_def):
            result = resolve_ff_hint("MysteryRock")
        assert result["is_submittable"] is False
        assert "missing parameterization.mode" in result["blocked_reason"]


class TestResolveFFHintBlockedPlaceholder:
    """Blocked placeholder additives → not submittable."""

    def test_blocked_placeholder(self):
        additive_def = {
            "category": "inorganic",
            "parameterization": {
                "mode": "inorganic_profile",
                "status": "blocked_placeholder",
            },
        }
        with _patch_db(additive_def=additive_def):
            result = resolve_ff_hint("NanoClay")
        assert result["is_submittable"] is False
        assert "blocked_placeholder" in result["blocked_reason"]
        # Even blocked, the FF hint reflects intent
        assert result["ff_hint"] == "interface_profile"
        assert result["ff_display_label"] == "INTERFACE (blocked)"


class TestResolveFFHintYamlError:
    """YAML load error scoping — only blocks additives, not SARA."""

    def test_yaml_error_blocks_additive(self):
        additive_def = {"category": "inorganic", "parameterization": {"mode": "inorganic_profile"}}
        with _patch_db(additive_def=additive_def, yaml_err=Exception("parse failed")):
            result = resolve_ff_hint("SiO2")
        assert result["is_submittable"] is False
        assert "YAML failed to load" in result["blocked_reason"]


class TestResolveFFHintFailClosed:
    """Wave 0: exception during SSOT resolution must fail-closed.

    The previous behavior was to swallow exceptions and return the default
    submittable=True, GAFF2 dict. That re-introduces the silent
    misrouting Wave 0 exists to prevent, so the contract has been
    inverted: any exception now blocks the molecule with a diagnostic
    reason.
    """

    def test_db_exception_blocks_submission(self):
        mock_db = MagicMock()
        mock_db.get_additive_definition.side_effect = RuntimeError("DB unavailable")
        with patch("api.deps.get_molecule_db", return_value=mock_db):
            result = resolve_ff_hint("anything")
        assert result["is_submittable"] is False
        assert "Force-field resolution failed" in (result["blocked_reason"] or "")
        assert "RuntimeError" in (result["blocked_reason"] or "")
        assert "DB unavailable" in (result["blocked_reason"] or "")

    def test_ff_assignment_exception_blocks_submission(self):
        mock_db = MagicMock()
        mock_db.get_additive_definition.return_value = None
        mock_db.get_additives_load_error.return_value = None
        mock_db.get_ff_assignment.side_effect = RuntimeError("ff_assignment cache corrupt")
        mock_db.get_ff_assignment_load_error.return_value = None
        with patch("api.deps.get_molecule_db", return_value=mock_db):
            result = resolve_ff_hint("U-AS-Thio-0293")
        assert result["is_submittable"] is False
        assert "ff_assignment cache corrupt" in (result["blocked_reason"] or "")

    def test_router_exception_blocks_submission(self):
        """Even a router-level exception must not silently open submission."""
        mock_db = MagicMock()
        mock_db.get_additive_definition.return_value = None
        mock_db.get_additives_load_error.return_value = None
        mock_db.get_ff_assignment.return_value = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "test_v1.json",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        mock_db.get_ff_assignment_load_error.return_value = None

        def _explode(*_args, **_kwargs):
            raise ValueError("router blew up")

        with (
            patch("api.deps.get_molecule_db", return_value=mock_db),
            patch("forcefield.typing_router.resolve_typing_strategy", side_effect=_explode),
        ):
            result = resolve_ff_hint("Toluene")
        assert result["is_submittable"] is False
        assert "router blew up" in (result["blocked_reason"] or "")


class TestResolveFFHintMatchesRouter:
    """resolve_ff_hint() must agree with the shared typing router."""

    def test_inorganic_active_matches_router(self):
        additive_def = {
            "category": "inorganic",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "silica_hydroxylated_v1",
            },
        }
        with _patch_db(additive_def=additive_def):
            result = resolve_ff_hint("SiO2")

        from forcefield.typing_router import TypingStrategy, resolve_typing_strategy

        decision = resolve_typing_strategy("SiO2", additive_def, None)
        assert decision.strategy == TypingStrategy.INORGANIC_PROFILE
        assert result["is_submittable"] is True
        assert result["ff_hint"] == "interface_profile"

    def test_blocked_placeholder_matches_router(self):
        additive_def = {
            "category": "inorganic",
            "parameterization": {
                "mode": "inorganic_profile",
                "status": "blocked_placeholder",
            },
        }
        with _patch_db(additive_def=additive_def):
            result = resolve_ff_hint("NanoClay")

        from forcefield.typing_router import TypingStrategy, resolve_typing_strategy

        decision = resolve_typing_strategy("NanoClay", additive_def, None)
        assert decision.strategy == TypingStrategy.BLOCKED
        assert result["is_submittable"] is False
        assert "blocked_placeholder" in result["blocked_reason"]


class TestResolveFFHintFfAssignmentSSOT:
    """Wave 0: ff_assignment SSOT drives route/status/blocked semantics."""

    def test_ff_assignment_ionic_blocks_submission(self):
        """Ionic species must be BLOCKED until Wave 3 activates the profile."""
        ff_assignment = {
            "route": "ionic_profile",
            "status": "blocked_placeholder",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        with _patch_db(additive_def=None, ff_assignment=ff_assignment):
            result = resolve_ff_hint("NaCl")
        assert result["is_submittable"] is False
        assert result["route"] == "ionic_profile"
        assert result["status"] == "blocked_placeholder"
        assert result["ff_hint"] == "ionic_profile"
        assert result["ff_display_label"] == "Ionic (curating)"

    def test_ff_assignment_organic_curated_active(self):
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "toluene_v1.json",
            "formal_charge": 0,
            "canonical_smiles": "Cc1ccccc1",
        }
        with _patch_db(additive_def=None, ff_assignment=ff_assignment), _patch_readiness_complete():
            result = resolve_ff_hint("Toluene")
        assert result["is_submittable"] is True
        assert result["route"] == "organic_curated_artifact"
        assert result["status"] == "active"
        assert result["ff_hint"] == "gaff2"
        assert result["artifact_warning"] is None

    def test_ff_assignment_inorganic_profile_active(self):
        additive_def = {
            "category": "inorganic",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "silica_hydroxylated_v1",
            },
        }
        ff_assignment = {
            "route": "inorganic_profile",
            "status": "active",
            "source_id": "silica_hydroxylated_v1",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        with _patch_db(additive_def=additive_def, ff_assignment=ff_assignment):
            result = resolve_ff_hint("SiO2")
        assert result["is_submittable"] is True
        assert result["route"] == "inorganic_profile"
        assert result["status"] == "active"
        assert result["ff_hint"] == "interface_profile"
        assert result["ff_display_label"] == "INTERFACE-derived inorganic"

    def test_ff_assignment_ssot_load_error_blocks_everything(self):
        with _patch_db(
            additive_def=None,
            ff_assignment=None,
            ff_err=RuntimeError("ff_assignment yaml parse failed"),
        ):
            result = resolve_ff_hint("U-AS-Thio-0293")
        assert result["is_submittable"] is False
        assert "ff_assignment SSOT failed to load" in (result["blocked_reason"] or "")
