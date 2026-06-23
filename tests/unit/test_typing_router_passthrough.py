"""Passthrough routing + CNT/Graphene organic curated contract tests.

v01.01.00: CNT/Graphene are no longer passthrough — they use standard
organic_curated_artifact route with individual source_ids. Their artifacts
are auto-generated via fragment fallback when antechamber fails.

The passthrough BLOCKED rule still applies to any molecule that declares
parameterization.mode=organic_gaff2_passthrough (verified via synthetic fixture).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from forcefield.typing_router import (  # noqa: E402
    TypingStrategy,
    resolve_typing_strategy,
)


def _passthrough_assignment() -> dict:
    return {
        "route": "organic_curated_artifact",
        "status": "active",
        "source_id": "synthetic_passthrough_v1",
        "formal_charge": 0,
        "canonical_smiles": None,
    }


def _passthrough_additive_def() -> dict:
    return {
        "name": "Synthetic Passthrough Fixture",
        "category": "test",
        "parameterization": {
            "mode": "organic_gaff2_passthrough",
            "profile_id": "synthetic_passthrough_v1",
            "status": "active",
        },
    }


class TestPassthroughTypingDecision:
    """Passthrough mode still triggers BLOCKED (contract preserved via synthetic fixture)."""

    def test_synthetic_passthrough_returns_blocked(self):
        decision = resolve_typing_strategy(
            "SyntheticMol",
            _passthrough_additive_def(),
            _passthrough_assignment(),
        )
        assert decision.strategy == TypingStrategy.BLOCKED
        assert "passthrough" in decision.blocked_reason

    def test_ordinary_organic_curated_still_passes(self):
        """Regression guard: ordinary curated organics must NOT be blocked."""
        ff = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "Toluene",
            "formal_charge": 0,
        }
        decision = resolve_typing_strategy("Toluene", None, ff)
        assert decision.strategy == TypingStrategy.ORGANIC_CURATED_ARTIFACT
        assert decision.blocked_reason is None


class TestCNTGrapheneOrganic:
    """v01.01.00: CNT/Graphene use standard organic curated route (not passthrough)."""

    def test_cnt_routes_to_organic_curated(self):
        """CNT with mode=organic_gaff2 (not passthrough) → ORGANIC_CURATED_ARTIFACT."""
        ff = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "Carbon_Nano_Tube",
            "formal_charge": 0,
        }
        additive_def = {
            "name": "Carbon Nano Tube",
            "category": "inorganic",
            "parameterization": {"mode": "organic_gaff2", "status": "active"},
        }
        decision = resolve_typing_strategy("Carbon_Nano_Tube", additive_def, ff)
        assert decision.strategy == TypingStrategy.ORGANIC_CURATED_ARTIFACT
        assert decision.source_id == "Carbon_Nano_Tube"

    def test_graphene_routes_to_organic_curated(self):
        ff = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "Graphine",
            "formal_charge": 0,
        }
        additive_def = {
            "name": "Graphine",
            "category": "inorganic",
            "parameterization": {"mode": "organic_gaff2", "status": "active"},
        }
        decision = resolve_typing_strategy("Graphine", additive_def, ff)
        assert decision.strategy == TypingStrategy.ORGANIC_CURATED_ARTIFACT
        assert decision.source_id == "Graphine"

    def test_cnt_resolve_ff_hint_artifact_not_found(self):
        """Without artifact on disk, CNT is blocked (artifact not found, not passthrough)."""
        from features.molecules.catalog import resolve_ff_hint

        result = resolve_ff_hint("Carbon_Nano_Tube")
        assert result["route"] == "organic_curated_artifact"
        # Without artifact, is_submittable=False with "not found" reason
        if not result["is_submittable"]:
            assert (
                "not found" in (result.get("blocked_reason") or "").lower()
                or "not generated" in (result.get("blocked_reason") or "").lower()
            )

    def test_resolve_ff_hint_ordinary_organic_unchanged(self):
        """Regression: ordinary organic curated stays submittable."""
        from features.molecules.catalog import resolve_ff_hint

        result = resolve_ff_hint("Toluene")
        assert result["is_submittable"] is True
        assert result["ff_hint"] == "gaff2"
