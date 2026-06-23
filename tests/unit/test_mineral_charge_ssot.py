"""Mineral charge SSOT regression tests.

Bind the three things that could drift apart:

1. The editable yaml SSOT (``data/forcefields/mineral_charge_catalog.yaml``)
   MUST equal the hardcoded fallback in ``builder.crystal_builder``.
2. ``CrystalBuilder.CHARGES`` MUST be populated from that SSOT.
3. Where a crystal material overlaps a curated CLAYFF profile in
   ``inorganic_profiles.yaml``, the bulk cation / bridging-anion charges MUST
   agree — except for an explicitly documented divergence allowlist, so a NEW
   inconsistency fails the suite while known gaps are tracked for reconciliation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from builder.crystal_builder import _CHARGES_HARDCODED_FALLBACK, CrystalBuilder
from common.pathing import get_project_root
from contracts.schemas import CrystalMaterial
from forcefield.mineral_charge_loader import (
    MineralChargeLoadError,
    load_mineral_charges,
)


def _inorganic_profiles() -> dict:
    path = get_project_root() / "data/forcefields/inorganic_profiles.yaml"
    return yaml.safe_load(path.read_text())


# material value -> (profile_id, {element: bulk_site_name})
_PROFILE_OVERLAP = {
    "SiO2": ("silica_hydroxylated_v1", {"Si": "Si_tet", "O": "O_br"}),
    "CaCO3": ("calcite_caco3_v1", {"Ca": "Ca_carb", "C": "C_carb", "O": "O_carb"}),
    "Al2O3": ("corundum_al2o3_v1", {"Al": "Al_oct", "O": "O_al"}),
}

# Reconciled in v01.05.22: Al2O3 → canonical CLAYFF (ao=+1.575, ob=-1.05) and
# CaCO3 → Raiteri-Gale (C=+1.123, O=-1.041), adopted in BOTH sources. The
# allowlist is now empty, so ANY divergence between the crystal-slab catalog and
# inorganic_profiles fails the suite.
_KNOWN_DIVERGENCES: set[tuple[str, str]] = set()


class TestSSOTEquivalence:
    def test_yaml_equals_hardcoded_fallback(self):
        """The loaded SSOT must match the hardcoded fallback value by value."""
        loaded = load_mineral_charges()
        # Map enum-keyed fallback to value-keyed for comparison.
        fallback = {mat.value: dict(ch) for mat, ch in _CHARGES_HARDCODED_FALLBACK.items()}
        assert loaded == fallback

    def test_crystalbuilder_charges_populated(self):
        """CrystalBuilder.CHARGES is populated from the SSOT for all materials."""
        assert CrystalBuilder.CHARGES == _CHARGES_HARDCODED_FALLBACK
        assert CrystalBuilder.CHARGES[CrystalMaterial.SIO2] == {"Si": 2.1, "O": -1.05}

    def test_loader_raises_on_missing_yaml(self, tmp_path):
        missing = tmp_path / "does_not_exist.yaml"
        with pytest.raises(MineralChargeLoadError):
            load_mineral_charges(path=missing)

    def test_loader_rejects_bad_schema(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("schema_version: 999\nmaterials: {SiO2: {Si: 2.1}}\n")
        with pytest.raises(MineralChargeLoadError):
            load_mineral_charges(path=bad)


class TestCrossConsistencyWithProfiles:
    def test_all_overlapping_materials_match_profiles(self):
        """Every overlapping material MUST match its curated profile, element by element.

        Binds SiO2 (CLAYFF), Al2O3 (CLAYFF), and CaCO3 (Raiteri-Gale) so the
        crystal-slab catalog and inorganic_profiles cannot diverge.
        """
        catalog = load_mineral_charges()
        profiles = _inorganic_profiles()["profiles"]
        for material, (profile_id, element_to_site) in _PROFILE_OVERLAP.items():
            sr = profiles[profile_id]["site_rules"]
            for element, site in element_to_site.items():
                assert catalog[material][element] == sr[site]["charge"], (
                    f"{material} {element}: catalog={catalog[material][element]} "
                    f"!= profile {profile_id}/{site}={sr[site]['charge']}"
                )

    def test_overlap_divergences_are_documented(self):
        """Any (material, element) charge divergence must be a known/tracked one.

        Binds the crystal-slab catalog to the curated profiles: a NEW divergence
        (drift) fails here; the existing calcite/corundum gaps are explicitly
        allowlisted for reconciliation.
        """
        catalog = load_mineral_charges()
        profiles = _inorganic_profiles()["profiles"]

        observed: set[tuple[str, str]] = set()
        for material, (profile_id, element_to_site) in _PROFILE_OVERLAP.items():
            sr = profiles[profile_id]["site_rules"]
            for element, site in element_to_site.items():
                cat_q = catalog[material][element]
                prof_q = sr[site]["charge"]
                if cat_q != prof_q:
                    observed.add((material, element))

        # No undocumented divergence (drift) is allowed.
        undocumented = observed - _KNOWN_DIVERGENCES
        assert undocumented == set(), (
            f"New charge divergence(s) between crystal catalog and inorganic_profiles: "
            f"{sorted(undocumented)}"
        )
        # Documented divergences that have been reconciled should be removed
        # from the allowlist (keeps the list honest).
        stale = _KNOWN_DIVERGENCES - observed
        assert stale == set(), f"Allowlist lists already-consistent pairs: {sorted(stale)}"


def test_catalog_file_exists_and_is_valid_yaml():
    path = get_project_root() / "data/forcefields/mineral_charge_catalog.yaml"
    assert path.exists()
    payload = yaml.safe_load(Path(path).read_text())
    assert payload["schema_version"] == 1
    assert "materials" in payload and payload["materials"]


def test_every_material_has_a_charge_source():
    """Provenance: every material declares an honest per-material charge source."""
    path = get_project_root() / "data/forcefields/mineral_charge_catalog.yaml"
    payload = yaml.safe_load(Path(path).read_text())
    materials = set(payload["materials"])
    sources = payload.get("charge_sources", {})
    missing = materials - set(sources)
    assert missing == set(), f"Materials missing a charge_source: {sorted(missing)}"
    # Sources must be non-empty strings.
    for mat in materials:
        assert isinstance(sources[mat], str) and sources[mat].strip(), (
            f"charge_source for {mat} is empty"
        )
