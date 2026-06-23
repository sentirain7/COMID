"""Wave 1 boost: lock the list_molecules / list_additives route enrichment.

These tests prevent regressions where the frontend's RouteBadge starts
seeing ``mol.route === undefined`` because someone trimmed the response
enrichment in ``features.molecules.catalog``.

Coverage:

* ``list_molecules`` page entries carry ``route`` and ``status`` from the
  ff_assignment SSOT.
* ``list_additives`` rows carry ``route``, ``status``,
  ``is_submittable`` and ``blocked_reason`` so the additive picker can
  render badges and disable blocked entries directly from the list
  endpoint without per-row resolve_ff_hint round-trips.
* ``resolve_ff_hint`` fail-closes (is_submittable=False with a
  diagnostic blocked_reason) when the underlying SSOT path raises —
  this is the Wave 0 boost contract that the new badge UI now depends
  on, so it must stay locked.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from contracts.schemas import MoleculeCategory, MoleculeSpec  # noqa: E402
from features.molecules.catalog import (  # noqa: E402
    list_additives,
    list_molecules,
    resolve_ff_hint,
)


def _make_spec(mol_id: str, category: MoleculeCategory) -> MoleculeSpec:
    return MoleculeSpec(
        mol_id=mol_id,
        smiles=f"[{mol_id}]",
        molecular_weight=100.0,
        atom_count=12,
        category=category,
        structure_file=f"single_moles/{mol_id}.mol",
        topology_hash="abc12345",
    )


def _patch_db_for_list(specs: dict[str, MoleculeSpec], ff_map: dict[str, dict | None]):
    """Build a MagicMock MoleculeDB that drives list_molecules."""
    mock_db = MagicMock()
    mock_db.list_all.return_value = list(specs.keys())
    mock_db.get.side_effect = lambda mid: specs.get(mid)
    mock_db.get_additive_definition.side_effect = lambda mid: None
    mock_db.get_additives_load_error.return_value = None
    mock_db.get_ff_assignment.side_effect = lambda mid: ff_map.get(mid)
    mock_db.get_ff_assignment_load_error.return_value = None
    return mock_db


class TestListMoleculesRouteEnrichment:
    """Wave 0 boost contract: list endpoint surfaces SSOT route/status."""

    def test_organic_curated_entry_carries_route_and_status(self):
        specs = {"Toluene": _make_spec("Toluene", MoleculeCategory.AROMATIC)}
        ff_map = {
            "Toluene": {
                "route": "organic_curated_artifact",
                "status": "active",
                "source_id": "toluene_v1.json",
                "formal_charge": 0,
                "canonical_smiles": "Cc1ccccc1",
            }
        }
        mock_db = _patch_db_for_list(specs, ff_map)
        # v00.99.96: artifact readiness is strict (missing artifact blocks
        # submit). This test focuses on route/status enrichment, so stub the
        # readiness probe to "complete" so the organic curated entry remains
        # submittable regardless of the fixture directory state.
        with (
            patch("api.deps.get_molecule_db", return_value=mock_db),
            patch(
                "features.molecules.catalog._get_organic_artifact_readiness",
                return_value={
                    "exists": True,
                    "complete": True,
                    "source_id": "toluene_v1.json",
                    "blocked_reason": None,
                },
            ),
        ):
            response = asyncio.run(list_molecules())

        assert response["total"] == 1
        entry = response["molecules"][0]
        assert entry["mol_id"] == "Toluene"
        # Contract: backend MUST send these to the UI
        assert "route" in entry, (
            "list_molecules dropped the 'route' field — frontend RouteBadge depends on this"
        )
        assert "status" in entry, "list_molecules dropped the 'status' field"
        assert entry["route"] == "organic_curated_artifact"
        assert entry["status"] == "active"
        assert entry["is_submittable"] is True

    def test_ionic_entry_is_blocked_with_user_friendly_reason(self):
        specs = {"NaCl": _make_spec("NaCl", MoleculeCategory.AROMATIC)}
        ff_map = {
            "NaCl": {
                "route": "ionic_profile",
                "status": "blocked_placeholder",
                "source_id": None,
                "formal_charge": 0,
                "canonical_smiles": None,
            }
        }
        mock_db = _patch_db_for_list(specs, ff_map)
        with patch("api.deps.get_molecule_db", return_value=mock_db):
            response = asyncio.run(list_molecules())

        entry = response["molecules"][0]
        assert entry["route"] == "ionic_profile"
        assert entry["status"] == "blocked_placeholder"
        assert entry["is_submittable"] is False
        assert entry["blocked_reason"]
        assert "ionic" in entry["blocked_reason"].lower()

    def test_legacy_entry_with_no_ff_assignment_still_renders(self):
        """Migration safety: if a yaml entry hasn't been promoted yet,
        the list endpoint must still return something the frontend can
        render — route may be None but the badge code must not crash."""
        specs = {"Legacy_Mol": _make_spec("Legacy_Mol", MoleculeCategory.SATURATE)}
        ff_map: dict[str, dict | None] = {"Legacy_Mol": None}
        mock_db = _patch_db_for_list(specs, ff_map)
        with patch("api.deps.get_molecule_db", return_value=mock_db):
            response = asyncio.run(list_molecules())

        entry = response["molecules"][0]
        # route is allowed to be None when no ff_assignment exists yet,
        # but the key must still be present so frontend `mol.route` is
        # `undefined → null` instead of throwing on missing field access.
        assert "route" in entry
        assert "status" in entry
        # Phase 6: molecules without ff_assignment are BLOCKED.
        assert entry["is_submittable"] is False


class TestListAdditivesRouteEnrichment:
    """Wave 0 boost contract: additive list endpoint surfaces route fields."""

    def test_additive_carries_route_and_blocked_state(self):
        # The catalog.list_additives helper materializes ORM rows via a
        # local _list closure passed to run_in_session. We bypass that
        # entire path by patching run_in_session to return canned dicts.
        additive_rows = [
            {
                "mol_id": "SiO2",
                "name": "Silicon Dioxide",
                "short_name": "SiO2",
                "atom_count": 84,
                "molecular_weight": 1177.51,
                "category": "inorganic",
                "default_counts": {"X1": 2, "X2": 4, "X3": 6},
                "structure_file": "additives/SiO2.mol",
            },
            {
                "mol_id": "NanoClay",
                "name": "Nanoclay",
                "short_name": "NanoClay",
                "atom_count": 200,
                "molecular_weight": 1500.0,
                "category": "inorganic",
                "default_counts": {"X1": 1, "X2": 2, "X3": 3},
                "structure_file": "additives/NanoClay.mol",
            },
        ]

        # We also need resolve_ff_hint to return a valid dict for these
        # mol_ids without hitting the real MoleculeDB. Patch it directly.
        def _fake_resolve(mol_id: str) -> dict:
            if mol_id == "SiO2":
                return {
                    "ff_hint": "interface_profile",
                    "ff_display_label": "INTERFACE-derived inorganic",
                    "parameterization_mode": "inorganic_profile",
                    "submit_ff_type": "bulk_ff_gaff2",
                    "is_submittable": True,
                    "blocked_reason": None,
                    "route": "inorganic_profile",
                    "status": "active",
                }
            return {
                "ff_hint": "interface_profile",
                "ff_display_label": "INTERFACE (blocked)",
                "parameterization_mode": "inorganic_profile",
                "submit_ff_type": "bulk_ff_gaff2",
                "is_submittable": False,
                "blocked_reason": "Inorganic additive 'NanoClay' uses a profile (montmorillonite_v1) that is still being curated",
                "route": "inorganic_profile",
                "status": "blocked_placeholder",
            }

        # list_additives lazy-imports `run_in_session` from features.common,
        # so patch the source module rather than the consumer.
        with (
            patch(
                "features.common.run_in_session",
                side_effect=lambda fn: additive_rows,
            ),
            patch("features.molecules.catalog.resolve_ff_hint", side_effect=_fake_resolve),
        ):
            response = asyncio.run(list_additives())

        items = response["additives"]
        assert len(items) == 2

        sio2 = next(a for a in items if a.mol_id == "SiO2")
        assert sio2.route == "inorganic_profile"
        assert sio2.status == "active"
        assert sio2.is_submittable is True
        assert sio2.blocked_reason is None

        nanoclay = next(a for a in items if a.mol_id == "NanoClay")
        assert nanoclay.route == "inorganic_profile"
        assert nanoclay.status == "blocked_placeholder"
        assert nanoclay.is_submittable is False
        assert nanoclay.blocked_reason
        assert "curated" in nanoclay.blocked_reason.lower()


class TestResolveFfHintFailClosedLockdown:
    """Wave 0 boost: resolve_ff_hint must NEVER silently default-open.

    The Wave 1 frontend RouteBadge taxonomy now depends on this for
    every list endpoint enrichment, so the original ``except Exception:
    pass`` regression must stay closed.
    """

    def test_db_exception_blocks_with_diagnostic_reason(self):
        mock_db = MagicMock()
        mock_db.get_additive_definition.side_effect = RuntimeError("db down")
        with patch("api.deps.get_molecule_db", return_value=mock_db):
            result = resolve_ff_hint("anything")
        assert result["is_submittable"] is False
        assert result["blocked_reason"]
        assert "RuntimeError" in result["blocked_reason"]

    def test_router_exception_does_not_silently_open(self):
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
            raise ValueError("router boom")

        with (
            patch("api.deps.get_molecule_db", return_value=mock_db),
            patch(
                "forcefield.typing_router.resolve_typing_strategy",
                side_effect=_explode,
            ),
        ):
            result = resolve_ff_hint("Toluene")
        assert result["is_submittable"] is False
        assert "router boom" in (result["blocked_reason"] or "")

    def test_ff_assignment_load_error_blocks_everything(self):
        mock_db = MagicMock()
        mock_db.get_additive_definition.return_value = None
        mock_db.get_additives_load_error.return_value = None
        mock_db.get_ff_assignment.return_value = None
        mock_db.get_ff_assignment_load_error.return_value = RuntimeError("yaml broken")
        with patch("api.deps.get_molecule_db", return_value=mock_db):
            result = resolve_ff_hint("U-AS-Thio-0293")
        assert result["is_submittable"] is False
        assert "ff_assignment SSOT failed to load" in (result["blocked_reason"] or "")
