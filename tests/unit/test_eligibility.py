"""Unit tests for FF eligibility adapter.

Tests that the eligibility helper correctly surfaces blocked/warning
states from existing SSOT (typing_router + ff_assignment).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from forcefield.eligibility import (  # noqa: E402
    collect_binder_ff_issues,
    collect_layered_ff_checks,
)


def _stub_resolve_ff_hint(mapping: dict[str, dict]):
    """Return a patch that replaces resolve_ff_hint with a dict lookup.

    Each value must include at least ``is_submittable``, ``blocked_reason``,
    ``artifact_warning``, ``route``, ``status`` to mirror the production
    return shape.
    """

    def _resolve(item_id: str) -> dict:
        return mapping.get(
            item_id,
            {
                "is_submittable": True,
                "blocked_reason": None,
                "artifact_warning": None,
                "route": "organic_curated_artifact",
                "status": "active",
            },
        )

    return patch("features.molecules.catalog.resolve_ff_hint", side_effect=_resolve)


class TestBinderFFIssues:
    """Binder composition FF eligibility."""

    def test_organic_molecules_have_no_issues(self):
        mapping = {
            "U-SA-Squalane-0293": {
                "is_submittable": True,
                "blocked_reason": None,
                "artifact_warning": None,
                "route": "organic_curated_artifact",
                "status": "active",
            },
        }
        with _stub_resolve_ff_hint(mapping):
            result = collect_binder_ff_issues(
                mol_ids=["U-SA-Squalane-0293"],
                additive_ids=[],
            )
        assert not result["has_blocked"]
        assert result["blocked_items"] == []
        assert result["warning_items"] == []

    def test_missing_artifact_surfaces_as_warning(self):
        """v00.99.30 historical: when resolve_ff_hint returns is_submittable=True
        with an artifact_warning set, the aggregator routes it to
        warning_items. This pre-v00.99.96 shape is no longer produced by
        resolve_ff_hint (see test_ff_strict_readiness for the new
        blocked-item routing), but the function's behaviour for this
        input shape is locked so any future non-organic warning channel
        can still use the warning_items slot."""
        mapping = {
            "U-SA-Squalane-0293": {
                "is_submittable": True,
                "blocked_reason": None,
                "artifact_warning": "Artifact not found for 'U-SA-Squalane-0293'.",
                "route": "organic_curated_artifact",
                "status": "active",
            },
        }
        with _stub_resolve_ff_hint(mapping):
            result = collect_binder_ff_issues(
                mol_ids=["U-SA-Squalane-0293"],
                additive_ids=[],
            )
        assert not result["has_blocked"]
        assert result["blocked_items"] == []
        assert len(result["warning_items"]) == 1
        w = result["warning_items"][0]
        assert w["item_id"] == "U-SA-Squalane-0293"
        assert w["item_kind"] == "molecule"
        assert w["status"] == "warn"
        assert "not found" in w["message"].lower()
        # Only the agreed fields are present — no categorisation extras.
        assert set(w) == {"item_id", "item_kind", "route", "status", "message"}

    def test_blocked_additive_surfaces(self):
        """H2SO4 is blocked → should appear in blocked_items."""
        mapping = {
            "H2SO4": {
                "is_submittable": False,
                "blocked_reason": "ionic_profile blocked_placeholder",
                "artifact_warning": None,
                "route": "ionic_profile",
                "status": "blocked_placeholder",
            },
        }
        with _stub_resolve_ff_hint(mapping):
            result = collect_binder_ff_issues(
                mol_ids=[],
                additive_ids=["H2SO4"],
            )
        assert result["has_blocked"]
        blocked_ids = [i["item_id"] for i in result["blocked_items"]]
        assert "H2SO4" in blocked_ids

    def test_sdbs_blocked_surfaces(self):
        """SDBS (Na surfactant) is blocked."""
        mapping = {
            "Emulsifiers_SodiumDodecylbenzeneSulfonate": {
                "is_submittable": False,
                "blocked_reason": "Sodium surfactant blocked",
                "artifact_warning": None,
                "route": "ionic_profile",
                "status": "blocked_placeholder",
            },
        }
        with _stub_resolve_ff_hint(mapping):
            result = collect_binder_ff_issues(
                mol_ids=[],
                additive_ids=["Emulsifiers_SodiumDodecylbenzeneSulfonate"],
            )
        assert result["has_blocked"]


class TestLayeredFFChecks:
    """Layered source stack FF compatibility."""

    def test_crystal_plus_binder_passes(self):
        layers = [
            {"source_type": "crystal_structure", "source_id": "test_crystal"},
            {"source_type": "binder_experiment", "source_id": "test_binder"},
        ]
        checks = collect_layered_ff_checks(layers)
        assert all(c["status"] == "pass" for c in checks)

    def test_unknown_source_type_fails_closed(self):
        layers = [
            {"source_type": "mystery_source", "source_id": "x"},
        ]
        checks = collect_layered_ff_checks(layers)
        fail_checks = [c for c in checks if c["status"] == "fail"]
        assert len(fail_checks) >= 1
        assert "unknown" in fail_checks[0]["message"].lower()

    def test_interface_molecule_without_source_id_fails(self):
        layers = [
            {"source_type": "interface_molecule", "source_id": None},
        ]
        checks = collect_layered_ff_checks(layers)
        fail_checks = [c for c in checks if c["status"] == "fail"]
        assert len(fail_checks) >= 1
        assert "missing" in fail_checks[0]["message"].lower()

    def test_interface_molecule_organic_passes(self):
        """Organic interface molecule (e.g., Toluene) should pass."""
        layers = [
            {"source_type": "crystal_structure", "source_id": "crystal1"},
            {"source_type": "interface_molecule_cell", "source_id": "Toluene"},
        ]
        checks = collect_layered_ff_checks(layers)
        fail_checks = [c for c in checks if c["status"] == "fail"]
        assert len(fail_checks) == 0

    def test_interface_molecule_water_passes(self):
        """Water model interface should pass."""
        layers = [
            {"source_type": "crystal_structure", "source_id": "crystal1"},
            {"source_type": "interface_molecule_cell", "source_id": "H2O"},
        ]
        checks = collect_layered_ff_checks(layers)
        fail_checks = [c for c in checks if c["status"] == "fail"]
        assert len(fail_checks) == 0
