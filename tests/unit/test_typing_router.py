"""Unit tests for the shared typing/charge strategy router.

Phase 6: ORGANIC_RDKIT_LEGACY has been removed. Legacy route strings
now resolve to BLOCKED. Tests updated accordingly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from forcefield.typing_router import (  # noqa: E402
    TypingStrategy,
    resolve_typing_strategy,
)


def _organic_curated_assignment():
    return {
        "route": "organic_curated_artifact",
        "status": "active",
        "source_id": "toluene_v1.json",
        "formal_charge": 0,
        "canonical_smiles": "Cc1ccccc1",
    }


class TestResolveTypingStrategyOrganic:
    """Post-Phase-6 organic routes (legacy additive_def branch).

    After Phase 6, molecules without ff_assignment are BLOCKED (not
    silently routed to the removed RDKit path).
    """

    def test_non_additive_without_ff_assignment_is_blocked(self):
        decision = resolve_typing_strategy("U-AS-Thio-0293", None)
        assert decision.strategy == TypingStrategy.BLOCKED
        assert "no ff_assignment" in decision.blocked_reason

    def test_organic_additive_no_ff_assignment_is_blocked(self):
        additive_def = {"category": "organic_polymer", "name": "SBS"}
        decision = resolve_typing_strategy("SBS", additive_def)
        assert decision.strategy == TypingStrategy.BLOCKED


class TestResolveTypingStrategyInorganic:
    """Active inorganic profile routes."""

    def test_inorganic_profile_returns_inorganic(self):
        additive_def = {
            "category": "inorganic",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "silica_hydroxylated_v1",
            },
        }
        decision = resolve_typing_strategy("SiO2", additive_def)
        assert decision.strategy == TypingStrategy.INORGANIC_PROFILE
        assert decision.profile_id == "silica_hydroxylated_v1"


class TestResolveTypingStrategyBlocked:
    """Fail-closed routes that mirror StructureBuilder semantics."""

    def test_blocked_placeholder_inorganic_returns_blocked(self):
        additive_def = {
            "category": "inorganic",
            "parameterization": {
                "mode": "inorganic_profile",
                "status": "blocked_placeholder",
            },
        }
        decision = resolve_typing_strategy("NanoClay", additive_def)
        assert decision.strategy == TypingStrategy.BLOCKED
        assert "blocked_placeholder" in decision.blocked_reason

    def test_blocked_placeholder_organic_returns_blocked(self):
        """Even non-inorganic blocked placeholders are rejected."""
        additive_def = {
            "category": "organic_polymer",
            "parameterization": {"status": "blocked_placeholder"},
        }
        decision = resolve_typing_strategy("DraftPolymer", additive_def)
        assert decision.strategy == TypingStrategy.BLOCKED

    def test_inorganic_missing_mode_returns_blocked(self):
        additive_def = {"category": "inorganic", "parameterization": {}}
        decision = resolve_typing_strategy("MysteryRock", additive_def)
        assert decision.strategy == TypingStrategy.BLOCKED
        assert "missing parameterization.mode" in decision.blocked_reason

    def test_inorganic_no_parameterization_section_returns_blocked(self):
        """No parameterization section at all also fails closed."""
        additive_def = {"category": "inorganic"}
        decision = resolve_typing_strategy("BareMineral", additive_def)
        assert decision.strategy == TypingStrategy.BLOCKED


class TestRouterStability:
    """Smoke tests that the router itself is stateless and side-effect free."""

    def test_repeated_calls_are_consistent(self):
        additive_def = {
            "category": "inorganic",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "silica_hydroxylated_v1",
            },
        }
        d1 = resolve_typing_strategy("SiO2", additive_def)
        d2 = resolve_typing_strategy("SiO2", additive_def)
        assert d1.strategy == d2.strategy
        assert d1.profile_id == d2.profile_id

    def test_decision_repr(self):
        decision = resolve_typing_strategy("X", None)
        # Just checking that __repr__ does not raise
        assert "TypingRouterDecision" in repr(decision)


class TestResolveTypingStrategyFfAssignmentSSOT:
    """ff_assignment SSOT branch takes precedence over additive_def."""

    def test_retired_organic_rdkit_legacy_route_is_blocked(self):
        """Phase 6: organic_rdkit_legacy is a retired route => BLOCKED."""
        ff_assignment = {
            "route": "organic_rdkit_legacy",
            "status": "active",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        decision = resolve_typing_strategy("Toluene", None, ff_assignment)
        assert decision.strategy == TypingStrategy.BLOCKED
        assert "retired" in decision.blocked_reason.lower()

    def test_organic_opls_artifact_is_retired_route(self):
        """GAFF2 transition: organic_opls_artifact is now a retired route => BLOCKED."""
        ff_assignment = {
            "route": "organic_opls_artifact",
            "status": "active",
            "source_id": "toluene_opls_v1.json",
            "formal_charge": 0,
            "canonical_smiles": "Cc1ccccc1",
        }
        decision = resolve_typing_strategy("Toluene", None, ff_assignment)
        assert decision.strategy == TypingStrategy.BLOCKED
        assert "retired" in decision.blocked_reason.lower()

    def test_organic_curated_artifact_active(self):
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "toluene_v2.json",
            "formal_charge": 0,
            "canonical_smiles": "Cc1ccccc1",
        }
        decision = resolve_typing_strategy("Toluene", None, ff_assignment)
        assert decision.strategy == TypingStrategy.ORGANIC_CURATED_ARTIFACT
        assert decision.source_id == "toluene_v2.json"
        assert decision.blocked_reason is None

    def test_inorganic_profile_via_ff_assignment(self):
        ff_assignment = {
            "route": "inorganic_profile",
            "status": "active",
            "source_id": "silica_hydroxylated_v1",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        decision = resolve_typing_strategy("SiO2", None, ff_assignment)
        assert decision.strategy == TypingStrategy.INORGANIC_PROFILE
        assert decision.profile_id == "silica_hydroxylated_v1"
        assert decision.source_id == "silica_hydroxylated_v1"

    def test_inorganic_profile_missing_source_id_blocked(self):
        ff_assignment = {
            "route": "inorganic_profile",
            "status": "active",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        decision = resolve_typing_strategy("MysteryMineral", None, ff_assignment)
        assert decision.strategy == TypingStrategy.BLOCKED
        assert "source_id is missing" in decision.blocked_reason

    def test_ionic_profile_blocks_until_wave3(self):
        """NaCl / CaCl2 / NaOH etc must never silently misroute to organic."""
        ff_assignment = {
            "route": "ionic_profile",
            "status": "blocked_placeholder",
            "source_id": "NaCl",
            "profile_id": "joung_cheatham_nacl_v1",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        decision = resolve_typing_strategy("NaCl", None, ff_assignment)
        assert decision.strategy == TypingStrategy.BLOCKED
        reason = decision.blocked_reason or ""
        assert "Wave 3" in reason
        assert "ionic" in reason.lower()
        assert "NaCl" in reason

    def test_ionic_profile_active_with_artifact_routes_through(self):
        """With status=active and artifact on disk, ionic routes to IONIC_PROFILE."""
        ff_assignment = {
            "route": "ionic_profile",
            "status": "active",
            "source_id": "NaCl",
            "profile_id": "joung_cheatham_nacl_v1",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        # NaCl has a generated artifact on disk
        decision = resolve_typing_strategy("NaCl", None, ff_assignment)
        assert decision.strategy == TypingStrategy.IONIC_PROFILE
        assert decision.source_id == "NaCl"
        assert decision.profile_id == "joung_cheatham_nacl_v1"

    def test_ionic_profile_active_without_artifact_blocks(self):
        """With status=active but no artifact on disk, ionic is BLOCKED."""
        ff_assignment = {
            "route": "ionic_profile",
            "status": "active",
            "source_id": "FakeIon",
            "profile_id": "joung_cheatham_fake_v1",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        # FakeIon does not have an artifact on disk
        decision = resolve_typing_strategy("FakeIon", None, ff_assignment)
        assert decision.strategy == TypingStrategy.BLOCKED
        assert "artifact not yet generated" in decision.blocked_reason

    def test_unknown_route_is_blocked(self):
        ff_assignment = {
            "route": "made_up_route",
            "status": "active",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        decision = resolve_typing_strategy("X", None, ff_assignment)
        assert decision.strategy == TypingStrategy.BLOCKED
        assert "unknown ff_assignment.route" in decision.blocked_reason

    def test_ff_assignment_blocked_placeholder_overrides_route(self):
        """status=blocked_placeholder wins over any route value."""
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "blocked_placeholder",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        decision = resolve_typing_strategy("DraftOrganic", None, ff_assignment)
        assert decision.strategy == TypingStrategy.BLOCKED

    def test_ff_assignment_takes_precedence_over_additive_def(self):
        """ff_assignment route is authoritative for non-passthrough entries.

        Phase 2 (v00.99.41) caveat: ``parameterization.mode ==
        "organic_gaff2_passthrough"`` is now a fail-closed signal because
        no AM1-BCC executor exists for passthrough entries. To keep the
        original "ff_assignment is authoritative" intent, this test now
        uses an ordinary (non-passthrough) parameterization.mode so the
        ff_assignment.route still wins.
        """
        additive_def = {
            "category": "organic_polymer",
            "parameterization": {"mode": "organic_gaff2"},
        }
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "sbs_gaff2_v1.json",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        decision = resolve_typing_strategy("SBS", additive_def, ff_assignment)
        assert decision.strategy == TypingStrategy.ORGANIC_CURATED_ARTIFACT
        assert decision.source_id == "sbs_gaff2_v1.json"

    def test_passthrough_mode_blocks_even_when_route_is_curated(self):
        """Phase 2 (v00.99.41): passthrough mode is fail-closed.

        Counter-test to the previous case — when additive_def.parameterization
        .mode is organic_gaff2_passthrough, the typing layer must BLOCK
        regardless of ff_assignment.route claiming organic_curated_artifact.
        Rationale: shared source_id + no executor.
        """
        additive_def = {
            "category": "inorganic",
            "subcategory": "nanoparticle",
            "parameterization": {
                "mode": "organic_gaff2_passthrough",
                "profile_id": "carbon_sp2_passthrough_v1",
            },
        }
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "carbon_sp2_passthrough_v1",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        decision = resolve_typing_strategy("Carbon_Nano_Tube", additive_def, ff_assignment)
        assert decision.strategy == TypingStrategy.BLOCKED
        assert "passthrough" in decision.blocked_reason

    def test_legacy_route_strings_map_to_blocked(self):
        """Phase 6: legacy enum values map to BLOCKED via _missing_()."""
        assert TypingStrategy("organic_rdkit_legacy") == TypingStrategy.BLOCKED
        assert TypingStrategy("organic_typing") == TypingStrategy.BLOCKED

    def test_empty_route_in_ff_assignment_blocks(self):
        ff_assignment = {
            "route": "",
            "status": "active",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        decision = resolve_typing_strategy("PartialEntry", None, ff_assignment)
        assert decision.strategy == TypingStrategy.BLOCKED
        assert "route is empty" in (decision.blocked_reason or "")

    def test_missing_route_key_in_ff_assignment_blocks(self):
        """ff_assignment dict that omits the 'route' key entirely fails closed."""
        ff_assignment = {
            "status": "active",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        decision = resolve_typing_strategy("PartialEntry", None, ff_assignment)
        assert decision.strategy == TypingStrategy.BLOCKED

    def test_ionic_block_message_is_user_friendly(self):
        """The ionic block reason must tell the user what to do."""
        ff_assignment = {
            "route": "ionic_profile",
            "status": "blocked_placeholder",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        decision = resolve_typing_strategy("NaCl", None, ff_assignment)
        reason = decision.blocked_reason or ""
        assert "NaCl" in reason
        assert "ionic" in reason.lower()
        assert "Wave 3" in reason or "surrogate" in reason


class TestWaterModelRoute:
    """Water model route must resolve to WATER_MODEL, not BLOCKED or organic."""

    def test_water_model_route_returns_water_model_strategy(self):
        ff_assignment = {
            "route": "water_model",
            "status": "active",
            "source_id": "H2O",
            "formal_charge": 0,
            "canonical_smiles": "O",
        }
        decision = resolve_typing_strategy("H2O", None, ff_assignment)
        assert decision.strategy == TypingStrategy.WATER_MODEL
        assert decision.source_id == "H2O"
        assert decision.blocked_reason is None

    def test_water_model_is_not_blocked(self):
        """water_model must be in _VALID_ROUTES — not treated as unknown."""
        ff_assignment = {
            "route": "water_model",
            "status": "active",
            "source_id": "H2O",
        }
        decision = resolve_typing_strategy("H2O", None, ff_assignment)
        assert decision.strategy != TypingStrategy.BLOCKED

    def test_water_model_is_not_organic(self):
        """water_model must NOT fall through to ORGANIC_CURATED_ARTIFACT."""
        ff_assignment = {
            "route": "water_model",
            "status": "active",
            "source_id": "H2O",
        }
        decision = resolve_typing_strategy("H2O", None, ff_assignment)
        assert decision.strategy != TypingStrategy.ORGANIC_CURATED_ARTIFACT
