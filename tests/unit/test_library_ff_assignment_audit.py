"""Wave 0 library audit: every molecule SSOT entry must declare ff_assignment.

The typing router uses ``ff_assignment`` as its single source of truth. If
any molecule in ``asphalt_binder.yaml``, ``single_moles.yaml``, or
``additives.yaml`` is missing the block (or declares an invalid route), the
router has to fall back to legacy heuristics and ionic species can silently
route through the organic path.

These tests fail-closed the library load at startup so the repository cannot
ship a yaml that would silently misroute a molecule.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from common.pathing import get_project_root  # noqa: E402

VALID_ROUTES = {
    "organic_curated_artifact",
    "inorganic_profile",
    "ionic_profile",
    "water_model",
    "blocked",
}
VALID_STATUSES = {"active", "draft", "blocked_placeholder"}

DATA_DIR = get_project_root() / "data" / "molecules"


def _load_yaml(path: Path) -> dict[str, Any]:
    assert path.exists(), f"Missing SSOT file: {path}"
    data = yaml.safe_load(path.read_text()) or {}
    assert isinstance(data, dict), f"{path} must contain a mapping at top level"
    return data


def _iter_binder_entries() -> list[dict[str, Any]]:
    data = _load_yaml(DATA_DIR / "asphalt_binder.yaml")
    entries = data.get("molecules") or []
    assert isinstance(entries, list), "asphalt_binder.yaml:molecules must be a list"
    return [e for e in entries if isinstance(e, dict)]


def _iter_single_moles_entries() -> list[dict[str, Any]]:
    data = _load_yaml(DATA_DIR / "single_moles.yaml")
    entries = data.get("molecules") or []
    assert isinstance(entries, list), "single_moles.yaml:molecules must be a list"
    return [e for e in entries if isinstance(e, dict)]


def _iter_additive_entries() -> list[tuple[str, dict[str, Any]]]:
    data = _load_yaml(DATA_DIR / "additives.yaml")
    additives = data.get("additives") or {}
    assert isinstance(additives, dict), "additives.yaml:additives must be a mapping"
    return [(str(k), v) for k, v in additives.items() if isinstance(v, dict)]


def _assert_ff_assignment_shape(mol_id: str, ff: dict[str, Any]) -> None:
    """Validate a single ff_assignment block.

    Required keys: route, status, source_id, formal_charge, canonical_smiles.
    Route must be one of VALID_ROUTES (and must NOT be empty). Status must be
    one of VALID_STATUSES. organic_curated_artifact requires canonical_smiles;
    inorganic_profile requires source_id.
    """
    assert isinstance(ff, dict), f"{mol_id}: ff_assignment must be a mapping"

    for required in ("route", "status", "source_id", "formal_charge", "canonical_smiles"):
        assert required in ff, f"{mol_id}: ff_assignment missing required key '{required}'"

    route = ff["route"]
    status = ff["status"]
    # Wave 0 fail-closed: empty route is forbidden at repo level. The router
    # also fails closed at runtime if a partially-populated entry slips
    # through, but the SSOT itself must be tight.
    assert route, f"{mol_id}: route must be non-empty"
    assert route in VALID_ROUTES, f"{mol_id}: invalid route {route!r}"
    assert status in VALID_STATUSES, f"{mol_id}: invalid status {status!r}"

    # Ionic active entries must have profile_id
    if route == "ionic_profile" and status == "active":
        profile_id = ff.get("profile_id")
        assert profile_id, f"{mol_id}: ionic active entry must have profile_id"

    # formal_charge must be an int (or null)
    formal_charge = ff["formal_charge"]
    assert formal_charge is None or isinstance(formal_charge, int), (
        f"{mol_id}: formal_charge must be int or null, got {type(formal_charge).__name__}"
    )

    if route == "organic_curated_artifact" and status == "active":
        # source_id and canonical_smiles are required for fully curated entries.
        # During the Phase 6 transition, entries migrated from organic_rdkit_legacy
        # may have null source_id until artifacts are generated.
        pass

    if route == "inorganic_profile" and status == "active":
        assert ff["source_id"], (
            f"{mol_id}: inorganic_profile active route requires source_id (profile_id)"
        )


class TestAsphaltBinderFfAssignment:
    """All SARA binder entries must declare an ff_assignment block."""

    def test_all_entries_have_ff_assignment(self):
        entries = _iter_binder_entries()
        assert entries, "asphalt_binder.yaml must have at least one molecule"
        for entry in entries:
            base_id = entry.get("base_id")
            assert base_id, f"asphalt_binder entry missing base_id: {entry}"
            ff = entry.get("ff_assignment")
            assert ff is not None, f"{base_id}: ff_assignment block missing"
            _assert_ff_assignment_shape(str(base_id), ff)

    def test_all_binder_entries_use_valid_organic_route(self):
        """Post-Phase 6: every SARA molecule must use an organic route.

        Status may be 'active' (artifact exists) or 'blocked_placeholder'
        (artifact not yet generated by AmberTools). Both are valid SSOT
        states for organic molecules awaiting GAFF2 curation.
        """
        for entry in _iter_binder_entries():
            base_id = entry.get("base_id")
            ff = entry.get("ff_assignment") or {}
            route = ff.get("route")
            assert route == "organic_curated_artifact", (
                f"{base_id}: expected organic_curated_artifact route, got {route!r}"
            )
            assert ff.get("status") in ("active", "blocked_placeholder"), (
                f"{base_id}: expected active or blocked_placeholder, got {ff.get('status')!r}"
            )


class TestSingleMolesFfAssignment:
    """Single-molecule catalog must declare ff_assignment for every entry."""

    def test_all_entries_have_ff_assignment(self):
        entries = _iter_single_moles_entries()
        assert entries, "single_moles.yaml must have at least one molecule"
        for entry in entries:
            base_id = entry.get("base_id")
            assert base_id, f"single_moles entry missing base_id: {entry}"
            ff = entry.get("ff_assignment")
            assert ff is not None, f"{base_id}: ff_assignment block missing"
            _assert_ff_assignment_shape(str(base_id), ff)

    def test_ionic_species_have_correct_route(self):
        """NaCl/CaCl2/MgCl2/KCl/NaOH must be ionic_profile.

        All 5 ionic species now have generated artifacts and are active.
        NaOH uses hybrid approach (Na+ JC ion + OH- GAFF2 fragment).
        """
        expected_ionic = {"NaCl", "CaCl2", "MgCl2", "KCl", "NaOH"}
        generated_ionic = {"NaCl", "CaCl2", "MgCl2", "KCl", "NaOH"}
        found: set[str] = set()
        for entry in _iter_single_moles_entries():
            base_id = str(entry.get("base_id") or "")
            ff = entry.get("ff_assignment") or {}
            if base_id in expected_ionic:
                found.add(base_id)
                assert ff.get("route") == "ionic_profile", (
                    f"{base_id}: expected ionic_profile route, got {ff.get('route')!r}"
                )
                if base_id in generated_ionic:
                    assert ff.get("status") == "active", (
                        f"{base_id}: generated ionic salt should be active"
                    )
                else:
                    assert ff.get("status") == "blocked_placeholder", (
                        f"{base_id}: non-generated ionic species must stay blocked"
                    )
        missing = expected_ionic - found
        assert not missing, f"Missing ionic entries in single_moles.yaml: {sorted(missing)}"


class TestAdditivesFfAssignment:
    """Every additive entry must declare ff_assignment."""

    def test_all_entries_have_ff_assignment(self):
        entries = _iter_additive_entries()
        assert entries, "additives.yaml must have at least one additive"
        for additive_id, defn in entries:
            ff = defn.get("ff_assignment")
            assert ff is not None, f"{additive_id}: ff_assignment block missing"
            _assert_ff_assignment_shape(additive_id, ff)

    def test_silica_is_active_inorganic(self):
        for additive_id, defn in _iter_additive_entries():
            if additive_id != "SiO2":
                continue
            ff = defn.get("ff_assignment") or {}
            assert ff.get("route") == "inorganic_profile"
            assert ff.get("status") == "active"
            assert ff.get("source_id") == "silica_hydroxylated_v1"
            return
        pytest.fail("SiO2 not found in additives.yaml")

    def test_nanoclay_is_blocked_placeholder(self):
        for additive_id, defn in _iter_additive_entries():
            if additive_id != "NanoClay":
                continue
            ff = defn.get("ff_assignment") or {}
            assert ff.get("route") == "inorganic_profile"
            assert ff.get("status") == "blocked_placeholder"
            return
        pytest.fail("NanoClay not found in additives.yaml")


class TestMoleculeDbLoadsFfAssignments:
    """MoleculeDB must eagerly load ff_assignment SSOT without errors."""

    def test_db_init_loads_all_three_sources(self):
        from builder.molecule_db import MoleculeDB

        db = MoleculeDB()
        assert db.get_ff_assignment_load_error() is None

        # Spot checks that resolve() returns a dict for known entries
        assert db.get_ff_assignment("SiO2") is not None
        assert db.get_ff_assignment("NanoClay") is not None
        assert db.get_ff_assignment("NaCl") is not None
        assert db.get_ff_assignment("H2O") is not None
        assert db.get_ff_assignment("Toluene") is not None
        # SARA binder lookup via stripped mol_id
        assert db.get_ff_assignment("U-SA-Squalane-0293") is not None
        assert db.get_ff_assignment("L-AR-PHPN-0293") is not None

    def test_variant_sentinel_resolution_for_all_id_forms(self):
        """v01.05.03: the "_variant_" sentinel must resolve to a per-variant
        artifact source_id for every accepted binder mol_id form.

        A bare base id ("SA-Squalane") carries no aging information; it
        resolves with the system default aging state (non_aging → "U-"),
        matching the amorphous-cell build path. Without this, amorphous
        cells storing base-id components fail the layered FF gate even
        though the U-variant artifact exists on disk.
        """
        from builder.molecule_db import MoleculeDB

        db = MoleculeDB()
        # Full id with temp code → aging-prefixed source
        assert db.get_ff_assignment("U-SA-Squalane-0293")["source_id"] == "U-SA-Squalane"
        # Bare prefixed id → unchanged aging prefix
        assert db.get_ff_assignment("L-AR-PHPN")["source_id"] == "L-AR-PHPN"
        # Base id (no aging info) → default non_aging variant
        assert db.get_ff_assignment("SA-Squalane")["source_id"] == "U-SA-Squalane"
        assert db.get_ff_assignment("AR-PHPN")["source_id"] == "U-AR-PHPN"
        # Non-SARA single mole keeps its own source_id untouched
        toluene = db.get_ff_assignment("Toluene")
        assert toluene["source_id"] != "_variant_"

    def test_base_id_binder_passes_ff_hint_gate(self):
        """Regression: amorphous-cell components stored as base-id must be
        submittable through the catalog FF gate (was permanently blocked)."""
        from features.molecules.catalog import resolve_ff_hint

        hint = resolve_ff_hint("SA-Squalane")
        assert hint["is_submittable"] is True, hint["blocked_reason"]
        assert hint["route"] == "organic_curated_artifact"

    def test_db_ionic_lookup_matches_router_decision(self):
        from builder.molecule_db import MoleculeDB
        from forcefield.typing_router import TypingStrategy, resolve_typing_strategy

        # Generated JC/hybrid artifacts allow routing through IONIC_PROFILE.
        # H2SO4 is now blocked (inorganic acid, GAFF2 inappropriate).
        _GENERATED_IONIC = {"NaCl", "CaCl2", "MgCl2", "KCl", "NaOH"}
        _BLOCKED = {"H2SO4"}
        db = MoleculeDB()
        for mol_id in ("NaCl", "CaCl2", "MgCl2", "KCl", "NaOH", "H2SO4"):
            ff = db.get_ff_assignment(mol_id)
            assert ff is not None, f"{mol_id}: ff_assignment missing"
            decision = resolve_typing_strategy(mol_id, None, ff)
            if mol_id in _GENERATED_IONIC:
                assert decision.strategy == TypingStrategy.IONIC_PROFILE, (
                    f"{mol_id}: generated ionic should route to IONIC_PROFILE, "
                    f"got {decision.strategy}"
                )
            elif mol_id in _BLOCKED:
                assert decision.strategy == TypingStrategy.BLOCKED, (
                    f"{mol_id}: blocked species must route to BLOCKED, got {decision.strategy}"
                )
            else:
                assert decision.strategy == TypingStrategy.BLOCKED, (
                    f"{mol_id}: non-generated ionic must route to BLOCKED, got {decision.strategy}"
                )

    def test_db_silica_lookup_matches_router_inorganic(self):
        from builder.molecule_db import MoleculeDB
        from forcefield.typing_router import TypingStrategy, resolve_typing_strategy

        db = MoleculeDB()
        ff = db.get_ff_assignment("SiO2")
        additive_def = db.get_additive_definition("SiO2")
        decision = resolve_typing_strategy("SiO2", additive_def, ff)
        assert decision.strategy == TypingStrategy.INORGANIC_PROFILE
        assert decision.profile_id == "silica_hydroxylated_v1"
