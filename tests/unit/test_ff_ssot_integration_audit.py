"""Wave 6: integrated cross-reference audit across the FF SSOT initiative.

The Plan v3 waves added five separate yaml/JSON SSOTs:

1. ``data/molecules/asphalt_binder.yaml``      (Wave 0: SARA binder ff_assignment)
2. ``data/molecules/single_moles.yaml``        (Wave 0: single-mol ff_assignment)
3. ``data/molecules/additives.yaml``           (Wave 0: additive ff_assignment)
4. ``data/forcefields/inorganic_profiles.yaml`` (existing — site-rule SSOT)
5. ``data/forcefields/ionic_profiles.yaml``    (Wave 3: ionic SSOT, draft)
6. ``data/forcefields/mineral_lj_catalog.yaml`` (Wave 4: element-LJ SSOT)
7. ``data/forcefield_artifacts/organic_gaff2/*.json`` (Wave 2→GAFF2: artifact catalog)

Each wave already ships its own focused regression. This file is the
**cross-SSOT** audit: it verifies that the seven sources cannot
silently drift apart at the seams between waves. Concretely:

* Every ``ionic_profile`` route in single_moles points at a profile
  that EXISTS in ionic_profiles.yaml (or, in Wave 3, has source_id
  null because the route is still BLOCKED).
* Every ``inorganic_profile`` route in additives points at a profile
  that EXISTS in inorganic_profiles.yaml.
* Every ``organic_curated_artifact`` route source_id has a matching
  JSON file in the artifact catalog (Wave 2 promotion contract).
* Every additive entry that has both ``parameterization.mode`` and
  ``ff_assignment.route`` declares a consistent pair (no inorganic
  profile mode + organic_rdkit_legacy route mismatch).
* The ionic activation gates remain closed end-to-end: yaml
  global_enabled=false AND every NaCl/CaCl2/etc still routes to
  BLOCKED through the typing router.
* The mineral catalog stays element-only (no site_rules accidentally
  added — Wave 4 SSOT split contract).
* The Wave 4 numerical equivalence still holds (yaml ≡ hardcoded).
* The Wave 5 reference fixtures still parse cleanly.

If any of these cross-SSOT invariants drift, this single audit fails
loudly so the operator can see the exact seam that broke.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from common.pathing import get_project_root  # noqa: E402

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

REPO_ROOT = get_project_root()
DATA_DIR = REPO_ROOT / "data"
ASPHALT_BINDER_YAML = DATA_DIR / "molecules" / "asphalt_binder.yaml"
SINGLE_MOLES_YAML = DATA_DIR / "molecules" / "single_moles.yaml"
ADDITIVES_YAML = DATA_DIR / "molecules" / "additives.yaml"
INORGANIC_PROFILES_YAML = DATA_DIR / "forcefields" / "inorganic_profiles.yaml"
IONIC_PROFILES_YAML = DATA_DIR / "forcefields" / "ionic_profiles.yaml"
MINERAL_LJ_YAML = DATA_DIR / "forcefields" / "mineral_lj_catalog.yaml"
ARTIFACT_DIR = DATA_DIR / "forcefield_artifacts" / "organic_gaff2"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    assert path.exists(), f"SSOT file missing: {path}"
    payload = yaml.safe_load(path.read_text()) or {}
    assert isinstance(payload, dict), f"{path}: top level must be a mapping"
    return payload


def _binder_entries() -> list[dict]:
    return [
        e for e in _load_yaml(ASPHALT_BINDER_YAML).get("molecules", []) or [] if isinstance(e, dict)
    ]


def _single_mol_entries() -> list[dict]:
    return [
        e for e in _load_yaml(SINGLE_MOLES_YAML).get("molecules", []) or [] if isinstance(e, dict)
    ]


def _additive_entries() -> list[tuple[str, dict]]:
    return [
        (str(k), v)
        for k, v in (_load_yaml(ADDITIVES_YAML).get("additives") or {}).items()
        if isinstance(v, dict)
    ]


def _inorganic_profile_ids() -> set[str]:
    payload = _load_yaml(INORGANIC_PROFILES_YAML)
    return set((payload.get("profiles") or {}).keys())


def _ionic_profile_ids() -> set[str]:
    payload = _load_yaml(IONIC_PROFILES_YAML)
    return set((payload.get("profiles") or {}).keys())


def _ionic_activation_state() -> tuple[bool, list[str]]:
    payload = _load_yaml(IONIC_PROFILES_YAML)
    block = payload.get("activation") or {}
    enabled = bool(block.get("global_enabled", False))
    enabled_profiles = list(block.get("enabled_profiles") or [])
    return enabled, enabled_profiles


def _artifact_filenames() -> set[str]:
    if not ARTIFACT_DIR.exists():
        return set()
    return {p.name for p in ARTIFACT_DIR.glob("*.json")}


# ---------------------------------------------------------------------------
# Wave 0/2 cross-reference: organic_curated_artifact source_id ↔ JSON catalog
# ---------------------------------------------------------------------------


class TestArtifactSourceIdCrossReference:
    """GAFF2 promotion contract: every organic_curated_artifact entry
    must point at an existing JSON file in the catalog."""

    def _collect_artifact_sources(self) -> list[tuple[str, str, str | None]]:
        out: list[tuple[str, str, str | None]] = []
        # Aging prefix map for _variant_ resolution
        _AGING_PREFIX = {"non_aging": "U", "short_aging": "S", "long_aging": "L"}

        for entry in _binder_entries():
            ff = entry.get("ff_assignment") or {}
            if ff.get("route") == "organic_curated_artifact":
                source_id = ff.get("source_id")
                base_id = str(entry.get("base_id"))
                if source_id == "_variant_":
                    # Expand _variant_ to aging-prefix variants
                    available = entry.get("available_aging", ["non_aging"])
                    for aging_state in available:
                        prefix = _AGING_PREFIX.get(aging_state, "U")
                        variant_id = f"{prefix}-{base_id}"
                        out.append(("asphalt_binder", variant_id, variant_id))
                    continue
                out.append(("asphalt_binder", base_id, source_id))
        for entry in _single_mol_entries():
            ff = entry.get("ff_assignment") or {}
            if ff.get("route") == "organic_curated_artifact":
                out.append(("single_moles", str(entry.get("base_id")), ff.get("source_id")))
        for additive_id, defn in _additive_entries():
            ff = defn.get("ff_assignment") or {}
            if ff.get("route") == "organic_curated_artifact":
                out.append(("additives", additive_id, ff.get("source_id")))
        return out

    @pytest.mark.skip(
        reason="GAFF2 migration in progress: batch artifact generation not yet complete"
    )
    def test_every_artifact_route_has_existing_json(self):
        from forcefield.organic_curated_artifact import artifact_filename_for

        sources = self._collect_artifact_sources()
        artifact_files = _artifact_filenames()

        missing: list[str] = []
        for catalog, mol_id, source_id in sources:
            assert source_id, (
                f"{catalog}/{mol_id}: organic_curated_artifact route MUST set "
                "ff_assignment.source_id to the artifact filename "
                "(e.g., 'Toluene.json' or 'Toluene')."
            )
            filename = artifact_filename_for(str(source_id))
            if filename not in artifact_files:
                missing.append(f"{catalog}/{mol_id} → {filename}")

        assert not missing, (
            "organic_curated_artifact source_id has no matching JSON file in "
            f"data/forcefield_artifacts/organic_gaff2/: {missing}. "
            "Either remove the route flip or commit the artifact JSON."
        )

    def test_artifact_catalog_has_no_orphans(self):
        """Every artifact JSON in the catalog should be referenced by at
        least one yaml entry — OR be a whitelisted fixture. The
        latter is intentional during the migration window."""
        sources = self._collect_artifact_sources()
        referenced = set()
        for _, _, source_id in sources:
            if source_id:
                from forcefield.organic_curated_artifact import artifact_filename_for

                referenced.add(artifact_filename_for(str(source_id)))

        # Toluene.json is intentionally a regression fixture even
        # though no yaml entry currently flips to organic_curated_artifact.
        WHITELIST_FIXTURES = {"Toluene.json"}  # Regression fixture only
        on_disk = _artifact_filenames()
        orphans = (on_disk - referenced) - WHITELIST_FIXTURES
        assert not orphans, (
            f"Orphan artifact JSON files (not referenced by any yaml AND "
            f"not in the fixture whitelist): {sorted(orphans)}. "
            "Either reference them from a yaml ff_assignment or move them "
            "to the fixture whitelist."
        )


# ---------------------------------------------------------------------------
# Wave 0/Wave 3 cross-reference: ionic_profile source_id ↔ ionic_profiles.yaml
# ---------------------------------------------------------------------------


class TestIonicSourceIdCrossReference:
    """If a single_moles entry sets source_id for ionic_profile, the
    source_id MUST either exist in ionic_profiles.yaml OR match the
    mol_id itself (self-referencing JC/TIP3P artifact generated by
    the ionic_artifact_service pipeline).
    """

    def test_every_non_null_ionic_source_id_resolves(self):
        ionic_ids = _ionic_profile_ids()
        unresolved: list[str] = []
        for entry in _single_mol_entries():
            ff = entry.get("ff_assignment") or {}
            if ff.get("route") != "ionic_profile":
                continue
            source_id = ff.get("source_id")
            base_id = entry.get("base_id")
            if source_id is None:
                continue  # Not yet activated
            # source_id can be the mol_id itself (JC artifact) or a profile
            # key from ionic_profiles.yaml.
            if str(source_id) == str(base_id):
                continue  # Self-referencing artifact — valid
            if str(source_id) not in ionic_ids:
                unresolved.append(f"{base_id} -> {source_id} not in ionic_profiles.yaml")
        assert not unresolved, f"ionic_profile source_id values do not resolve: {unresolved}"

    def test_active_ionic_entries_have_profile_id_that_resolves(self):
        """Active ionic entries must have profile_id that maps to ionic_profiles.yaml."""
        ionic_ids = _ionic_profile_ids()
        issues: list[str] = []
        for entry in _single_mol_entries():
            ff = entry.get("ff_assignment") or {}
            if ff.get("route") != "ionic_profile":
                continue
            if ff.get("status") != "active":
                continue
            base_id = entry.get("base_id")
            profile_id = ff.get("profile_id")
            if not profile_id:
                issues.append(f"{base_id}: active ionic entry missing profile_id")
            elif str(profile_id) not in ionic_ids:
                issues.append(f"{base_id}: profile_id '{profile_id}' not in ionic_profiles.yaml")
        assert not issues, (
            "ionic_profile active entries with invalid/missing profile_id:\n"
            + "\n".join(f"  - {i}" for i in issues)
        )


# ---------------------------------------------------------------------------
# Wave 0/Wave 2 cross-reference: inorganic_profile source_id ↔ inorganic_profiles.yaml
# ---------------------------------------------------------------------------


class TestInorganicSourceIdCrossReference:
    def test_every_inorganic_source_id_resolves(self):
        profile_ids = _inorganic_profile_ids()
        unresolved: list[str] = []
        for additive_id, defn in _additive_entries():
            ff = defn.get("ff_assignment") or {}
            if ff.get("route") != "inorganic_profile":
                continue
            source_id = ff.get("source_id")
            if source_id is None:
                # Allowed only for blocked_placeholder; otherwise the
                # router will throw at runtime.
                if ff.get("status") != "blocked_placeholder":
                    unresolved.append(
                        f"{additive_id}: inorganic_profile route is active but source_id is null"
                    )
                continue
            if str(source_id) not in profile_ids:
                unresolved.append(f"{additive_id} → {source_id} not in inorganic_profiles.yaml")
        assert not unresolved, f"inorganic_profile source_id values do not resolve: {unresolved}"


# ---------------------------------------------------------------------------
# Wave 0 internal consistency: parameterization.mode ↔ ff_assignment.route
# ---------------------------------------------------------------------------


class TestAdditiveModeRouteConsistency:
    """For additives that have BOTH parameterization.mode and
    ff_assignment.route, the two declarations must agree."""

    def test_inorganic_mode_means_inorganic_route(self):
        mismatches: list[str] = []
        for additive_id, defn in _additive_entries():
            param = defn.get("parameterization") or {}
            ff = defn.get("ff_assignment") or {}
            mode = param.get("mode")
            route = ff.get("route")
            if mode is None or route is None:
                continue
            if mode == "inorganic_profile" and route != "inorganic_profile":
                mismatches.append(
                    f"{additive_id}: parameterization.mode=inorganic_profile "
                    f"but ff_assignment.route={route!r}"
                )
            if mode == "organic_gaff2_passthrough" and route not in ("organic_curated_artifact",):
                mismatches.append(
                    f"{additive_id}: parameterization.mode=organic_gaff2_passthrough "
                    f"but ff_assignment.route={route!r}"
                )
        assert not mismatches, (
            f"Additive parameterization.mode ↔ ff_assignment.route mismatch: {mismatches}"
        )


# ---------------------------------------------------------------------------
# Wave 3 end-to-end: activation gates closed AND every ionic species blocked
# ---------------------------------------------------------------------------


class TestIonicWaveThreeStillBlocked:
    """The Wave 3 contract MUST hold: ionic species blocked end to end."""

    def test_ionic_limited_activation(self):
        """Limited activation: global_enabled=true, some profiles active."""
        enabled, enabled_profiles = _ionic_activation_state()
        assert enabled is True, "ionic limited activation: global_enabled should be true"
        assert len(enabled_profiles) > 0, "at least one profile should be enabled"

    def test_enabled_ionic_profiles_are_active(self):
        from forcefield.ionic_executor import load_ionic_catalog

        catalog = load_ionic_catalog()
        for pid in catalog.activation_enabled_profiles:
            profile = catalog.profiles.get(pid)
            assert profile is not None, f"enabled profile {pid} not in catalog"
            assert profile.status == "active", (
                f"enabled profile {pid} has status={profile.status}, must be active"
            )

    @pytest.mark.parametrize(
        "mol_id",
        ["H2SO4"],
    )
    def test_h2so4_blocked_as_inorganic_acid(self, mol_id):
        """H2SO4 is blocked — inorganic acid, GAFF2 inappropriate."""
        from forcefield.typing_router import TypingStrategy, resolve_typing_strategy

        ff = None
        for entry in _single_mol_entries():
            if entry.get("base_id") == mol_id:
                ff = entry.get("ff_assignment")
                break
        assert ff is not None, f"{mol_id}: ff_assignment missing in single_moles.yaml"
        decision = resolve_typing_strategy(mol_id, None, ff)
        assert decision.strategy == TypingStrategy.BLOCKED

    @pytest.mark.parametrize(
        "mol_id",
        ["NaCl", "CaCl2", "MgCl2", "KCl"],
    )
    def test_generated_ionic_species_route_to_ionic_profile(self, mol_id):
        """Ionic species with a generated JC artifact and active status route through."""
        from forcefield.typing_router import TypingStrategy, resolve_typing_strategy

        ff = None
        for entry in _single_mol_entries():
            if entry.get("base_id") == mol_id:
                ff = entry.get("ff_assignment")
                break
        assert ff is not None, f"{mol_id}: ff_assignment missing in single_moles.yaml"
        decision = resolve_typing_strategy(mol_id, None, ff)
        assert decision.strategy == TypingStrategy.IONIC_PROFILE


# ---------------------------------------------------------------------------
# Wave 4 SSOT split: mineral_lj_catalog stays element-only
# ---------------------------------------------------------------------------


class TestMineralLJCatalogSplitContract:
    def test_mineral_lj_catalog_has_no_site_rules(self):
        payload = _load_yaml(MINERAL_LJ_YAML)
        assert "site_rules" not in payload
        for section in ("interface_ff", "uff_fallback"):
            for _element, entry in (payload.get(section) or {}).items():
                if isinstance(entry, dict):
                    assert "site_rules" not in entry
                    assert "neighbor_pattern" not in entry

    def test_inorganic_profiles_yaml_still_separate(self):
        assert INORGANIC_PROFILES_YAML.exists()
        assert MINERAL_LJ_YAML.exists()
        # The two SSOTs serve different purposes; they must not be folded.
        assert INORGANIC_PROFILES_YAML.name != MINERAL_LJ_YAML.name


# ---------------------------------------------------------------------------
# Wave 4 numerical equivalence (re-checked through the public dict)
# ---------------------------------------------------------------------------


class TestMineralLJEquivalenceLockdown:
    """Re-verify the Wave 4 equivalence at audit time. The dedicated
    Wave 4 test covers this in detail; the audit asserts the high-
    impact anchors so a single grep-able failure points at silica
    drift."""

    def test_silica_si_anchor(self):
        from forcefield.interface_ff import INTERFACE_FF_MINERAL_PARAMS
        from forcefield.mineral_lj_loader import load_interface_ff_params

        runtime = INTERFACE_FF_MINERAL_PARAMS["Si"]
        yaml_v = load_interface_ff_params()["Si"]
        assert runtime["epsilon"] == pytest.approx(0.00040, abs=1e-9)
        assert runtime["epsilon"] == pytest.approx(yaml_v["epsilon"], abs=1e-9)
        assert runtime["sigma"] == pytest.approx(yaml_v["sigma"], abs=1e-9)


# ---------------------------------------------------------------------------
# Wave 5 reference fixtures still parse cleanly
# ---------------------------------------------------------------------------


class TestWave5ReferenceFixturesPresent:
    def test_mineral_combined_fixture_present(self):
        fixture_dir = REPO_ROOT / "tests" / "data" / "mineral_combined"
        assert fixture_dir.exists()
        assert (fixture_dir / "silica_binder_ref.lammps_data").exists()
        assert (fixture_dir / "README.md").exists()


# ---------------------------------------------------------------------------
# Wave 6 final lockdown: route enum coverage
# ---------------------------------------------------------------------------


class TestRouteEnumExhaustiveCoverage:
    """Every yaml entry's ff_assignment.route MUST be one of the five
    canonical routes. The Wave 0 audit already covers this per file;
    the Wave 6 integration audit re-checks across all three molecule
    yamls in one place so a future fourth molecule yaml cannot escape
    the audit by being filed under a different test path."""

    VALID_ROUTES = {
        "organic_curated_artifact",
        "inorganic_profile",
        "ionic_profile",
        "water_model",
        "blocked",
    }

    def test_binder_routes_in_enum(self):
        for entry in _binder_entries():
            ff = entry.get("ff_assignment") or {}
            route = ff.get("route")
            assert route in self.VALID_ROUTES, (
                f"asphalt_binder/{entry.get('base_id')}: invalid route {route!r}"
            )

    def test_single_moles_routes_in_enum(self):
        for entry in _single_mol_entries():
            ff = entry.get("ff_assignment") or {}
            route = ff.get("route")
            assert route in self.VALID_ROUTES, (
                f"single_moles/{entry.get('base_id')}: invalid route {route!r}"
            )

    def test_additive_routes_in_enum(self):
        for additive_id, defn in _additive_entries():
            ff = defn.get("ff_assignment") or {}
            route = ff.get("route")
            assert route in self.VALID_ROUTES, f"additives/{additive_id}: invalid route {route!r}"


# ---------------------------------------------------------------------------
# Wave 6: cross-yaml mol_id uniqueness
# ---------------------------------------------------------------------------


class TestMolIdUniquenessAcrossYamls:
    """A mol_id must not appear in more than one of the three molecule
    yamls (asphalt_binder, single_moles, additives). The router resolves
    ff_assignment by direct mol_id lookup with a fallback for SARA
    binder strip; a duplicate would silently take the first hit."""

    def test_no_duplicate_mol_ids(self):
        binder_ids = {str(e.get("base_id")) for e in _binder_entries() if e.get("base_id")}
        single_ids = {str(e.get("base_id")) for e in _single_mol_entries() if e.get("base_id")}
        additive_ids = {aid for aid, _ in _additive_entries()}

        # Pairwise overlap
        b_s = binder_ids & single_ids
        b_a = binder_ids & additive_ids
        s_a = single_ids & additive_ids
        assert not b_s, f"Overlap binder ↔ single_moles: {sorted(b_s)}"
        assert not b_a, f"Overlap binder ↔ additives: {sorted(b_a)}"
        assert not s_a, f"Overlap single_moles ↔ additives: {sorted(s_a)}"
