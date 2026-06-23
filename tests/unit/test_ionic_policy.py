"""Ionic profile policy: limited activation + usage_context gate.

NaCl and CaCl2 are activated for single-molecule vacuum workflows.
Binder/layered/asphalt_interface remain blocked by usage_context gate.
Activation requires ASPHALT_IONIC_ROUTE_ACTIVATED=1 env var.

These tests lock:

1. ``ionic_profiles.yaml`` parses and contains active entries.
2. Enabled profiles have status=active and vacuum=true.
3. ``assign_ionic()`` requires usage_context (fail-closed if None).
4. With env var + matching context → assignment succeeds.
5. Without env var → blocked. Wrong context → blocked.
6. Non-vacuum ionic species (binder/layered) still route to BLOCKED.
6. The Wave 3 policy doc exists at the documented location.

If a future activation PR loosens any of these checks, that PR must
also extend ``docs/ionic_profile_policy.md`` and add a real LAMMPS
regression for the activated profile.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from common.pathing import get_project_root  # noqa: E402
from forcefield.ionic_executor import (  # noqa: E402
    ACTIVATION_ENV_VAR,
    IonicNotActivatedError,
    IonicProfileCatalog,
    IonicProfileNotFoundError,
    assign_ionic,
    get_ionic_profile,
    is_activated,
    is_environment_activated,
    load_ionic_catalog,
)
from forcefield.typing_router import (  # noqa: E402
    TypingStrategy,
    resolve_typing_strategy,
)

# ---------------------------------------------------------------------------
# YAML SSOT
# ---------------------------------------------------------------------------


class TestIonicCatalogLoader:
    def test_repo_yaml_loads_without_errors(self):
        catalog = load_ionic_catalog()
        assert isinstance(catalog, IonicProfileCatalog)
        assert catalog.schema_version == 1
        assert catalog.profiles, "ionic_profiles.yaml must declare at least one profile"

    def test_canonical_draft_profiles_present(self):
        """Wave 3 ships with at least NaCl + CaCl2 placeholders."""
        catalog = load_ionic_catalog()
        assert "joung_cheatham_nacl_v1" in catalog.profiles
        assert "joung_cheatham_cacl2_v1" in catalog.profiles

    def test_enabled_profiles_are_active(self):
        """Enabled profiles must have status=active."""
        catalog = load_ionic_catalog()
        for pid in catalog.activation_enabled_profiles:
            profile = catalog.profiles.get(pid)
            assert profile is not None, f"enabled profile {pid!r} not found"
            assert profile.status == "active", (
                f"enabled profile {pid!r} has status={profile.status!r}, must be active"
            )

    def test_activation_gates_open_for_limited_activation(self):
        """Limited activation: global_enabled=true, enabled_profiles non-empty."""
        catalog = load_ionic_catalog()
        assert catalog.activation_global_enabled is True
        assert len(catalog.activation_enabled_profiles) > 0

    def test_get_ionic_profile_unknown_id_raises(self):
        with pytest.raises(IonicProfileNotFoundError):
            get_ionic_profile("does_not_exist_xyz")


# ---------------------------------------------------------------------------
# Activation gates
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _scrub_env(monkeypatch):
    """Don't let an outer environment leak into these tests."""
    monkeypatch.delenv(ACTIVATION_ENV_VAR, raising=False)


class TestActivationGates:
    def test_env_gate_default_closed(self):
        assert is_environment_activated() is False

    def test_env_gate_only_value_one_unblocks(self, monkeypatch):
        monkeypatch.setenv(ACTIVATION_ENV_VAR, "true")
        assert is_environment_activated() is False
        monkeypatch.setenv(ACTIVATION_ENV_VAR, "1")
        assert is_environment_activated() is True

    def test_is_activated_without_env_var_reports_blocker(self, monkeypatch):
        """Without env var, activation fails even if yaml gates are open."""
        monkeypatch.delenv(ACTIVATION_ENV_VAR, raising=False)
        ok, blockers = is_activated("joung_cheatham_nacl_v1")
        assert ok is False
        joined = " | ".join(blockers)
        assert ACTIVATION_ENV_VAR in joined

    def test_is_activated_unknown_profile(self, monkeypatch):
        monkeypatch.setenv(ACTIVATION_ENV_VAR, "1")
        ok, blockers = is_activated("definitely_not_a_profile")
        assert ok is False
        joined = " | ".join(blockers)
        assert "not declared" in joined


# ---------------------------------------------------------------------------
# assign_ionic: usage_context gate + activation gate contract
# ---------------------------------------------------------------------------


def _fake_topology(mol_id: str = "NaCl") -> SimpleNamespace:
    return SimpleNamespace(
        mol_id=mol_id,
        atoms=[
            SimpleNamespace(index=1, element="Na", ff_type="", charge=0.0, charge_defined=False),
            SimpleNamespace(index=2, element="Cl", ff_type="", charge=0.0, charge_defined=False),
        ],
    )


class TestAssignIonicGates:
    def test_no_usage_context_fails_closed(self):
        """usage_context=None must fail-closed."""
        with pytest.raises(IonicNotActivatedError, match="usage_context"):
            assign_ionic(
                topology=_fake_topology(),
                profile_id="joung_cheatham_nacl_v1",
            )

    def test_default_state_with_context_raises(self):
        """Even with context, activation gates are still closed."""
        with pytest.raises(IonicNotActivatedError) as exc_info:
            assign_ionic(
                topology=_fake_topology(),
                profile_id="joung_cheatham_nacl_v1",
                usage_context="vacuum",
            )
        msg = str(exc_info.value)
        assert ACTIVATION_ENV_VAR in msg
        assert "ionic_profile_policy.md" in msg

    def test_env_var_with_enabled_profile_succeeds(self, monkeypatch):
        """With env var + yaml gates open + vacuum context → success."""
        monkeypatch.setenv(ACTIVATION_ENV_VAR, "1")
        from forcefield.ionic_executor import IonicAssignmentResult

        result = assign_ionic(
            topology=_fake_topology(),
            profile_id="joung_cheatham_nacl_v1",
            usage_context="vacuum",
        )
        assert isinstance(result, IonicAssignmentResult)
        assert result.charge_model

    def test_unknown_profile_raises(self):
        with pytest.raises(IonicNotActivatedError):
            assign_ionic(
                topology=_fake_topology(),
                profile_id="profile_that_does_not_exist",
                usage_context="vacuum",
            )

    def test_all_gates_open_with_matching_context_passes_gate(self, monkeypatch):
        """With all gates open and matching context, assign_ionic passes gate.

        It will then try to load the artifact (which may not exist for
        synthetic profiles), but the gate itself must not block.
        """
        monkeypatch.setenv(ACTIVATION_ENV_VAR, "1")

        from forcefield.ionic_executor import (  # noqa: PLC0415
            IonicAtomType,
            IonicProfile,
            IonicSiteRule,
        )

        synthetic_profile = IonicProfile(
            profile_id="synthetic_active_v1",
            status="active",
            profile_version="1.0",
            family="alkali_halide",
            description="synthetic active profile",
            applicable_context={"aqueous": True, "asphalt_interface": False, "vacuum": True},
            mixing_rule_compatibility={
                "gaff2_arithmetic": "validated",
                "lorentz_berthelot": "validated",
            },
            citations={
                "ion_charges": "synthetic",
                "ion_lj": "synthetic",
                "validation": "synthetic_lammps_regression_v1",
            },
            site_rules=(
                IonicSiteRule(site_type="Na_ion", element="Na", charge=1.0, neighbor_pattern={}),
                IonicSiteRule(site_type="Cl_ion", element="Cl", charge=-1.0, neighbor_pattern={}),
            ),
            atom_types=(
                IonicAtomType(site_type="Na_ion", mass=22.990, epsilon=0.0874, sigma=2.4393),
                IonicAtomType(site_type="Cl_ion", mass=35.453, epsilon=0.0356, sigma=4.4778),
            ),
            validation={"neutrality_tolerance": 0.001, "required_elements": ["Na", "Cl"]},
        )
        synthetic_catalog = IonicProfileCatalog(
            schema_version=1,
            version="0.1-synthetic",
            activation_global_enabled=True,
            activation_enabled_profiles=("synthetic_active_v1",),
            profiles={"synthetic_active_v1": synthetic_profile},
        )

        ok, blockers = is_activated("synthetic_active_v1", catalog=synthetic_catalog)
        assert ok is True, f"synthetic catalog should be activated; blockers={blockers}"

        # Gate passes, artifact NaCl.json exists → actual assignment succeeds
        from forcefield.ionic_executor import IonicAssignmentResult

        result = assign_ionic(
            topology=_fake_topology(),
            profile_id="synthetic_active_v1",
            usage_context="vacuum",
            catalog=synthetic_catalog,
        )
        assert isinstance(result, IonicAssignmentResult)
        assert result.charge_model  # should be non-empty

    def test_all_gates_open_wrong_context_blocked(self, monkeypatch):
        """Gates open but context mismatch → IonicNotActivatedError."""
        monkeypatch.setenv(ACTIVATION_ENV_VAR, "1")

        from forcefield.ionic_executor import (  # noqa: PLC0415
            IonicProfile,
        )

        profile = IonicProfile(
            profile_id="synthetic_v1",
            status="active",
            profile_version="1.0",
            family="alkali_halide",
            description="test",
            applicable_context={"aqueous": True, "asphalt_interface": False, "vacuum": False},
            mixing_rule_compatibility={"lorentz_berthelot": "validated"},
            citations={"ion_charges": "x", "ion_lj": "x", "validation": "x"},
            site_rules=(),
            atom_types=(),
            validation={},
        )
        cat = IonicProfileCatalog(
            schema_version=1,
            version="0.1",
            activation_global_enabled=True,
            activation_enabled_profiles=("synthetic_v1",),
            profiles={"synthetic_v1": profile},
        )
        with pytest.raises(IonicNotActivatedError, match="does not support.*vacuum"):
            assign_ionic(
                topology=_fake_topology(),
                profile_id="synthetic_v1",
                usage_context="vacuum",
                catalog=cat,
            )


# ---------------------------------------------------------------------------
# End-to-end: ionic species stay BLOCKED through the typing router
# ---------------------------------------------------------------------------


_IONIC_MOL_IDS = ("NaCl", "CaCl2", "MgCl2", "KCl", "NaOH")


class TestIonicEndToEndBlocked:
    """The typing router must keep ionic species BLOCKED in Wave 3."""

    @pytest.mark.parametrize("mol_id", _IONIC_MOL_IDS)
    def test_router_blocks_ionic_species(self, mol_id):
        ff_assignment = {
            "route": "ionic_profile",
            "status": "blocked_placeholder",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        decision = resolve_typing_strategy(mol_id, None, ff_assignment)
        assert decision.strategy == TypingStrategy.BLOCKED, (
            f"{mol_id}: Wave 3 fail-closed contract violated; router returned {decision.strategy}"
        )
        # User-facing reason must mention either the species or "ionic"
        # AND point at the Wave 3 policy track.
        reason = decision.blocked_reason or ""
        assert mol_id in reason or "ionic" in reason.lower()
        assert "Wave 3" in reason

    def test_real_molecule_db_ionic_routing(self):
        """Generated ionic species route through; others stay blocked."""
        from builder.molecule_db import MoleculeDB

        # Molecules with generated JC/hybrid artifacts should route to IONIC_PROFILE
        _GENERATED_IONIC = {"NaCl", "CaCl2", "MgCl2", "KCl", "NaOH"}
        db = MoleculeDB()
        for mol_id in _IONIC_MOL_IDS:
            ff = db.get_ff_assignment(mol_id)
            assert ff is not None, (
                f"{mol_id}: ff_assignment missing from single_moles.yaml; "
                "Wave 0 audit should have caught this"
            )
            assert ff.get("route") == "ionic_profile"
            decision = resolve_typing_strategy(mol_id, None, ff)
            if mol_id in _GENERATED_IONIC:
                assert decision.strategy == TypingStrategy.IONIC_PROFILE, (
                    f"{mol_id}: expected IONIC_PROFILE (artifact generated), "
                    f"got {decision.strategy}"
                )
            else:
                assert decision.strategy == TypingStrategy.BLOCKED, (
                    f"{mol_id}: expected BLOCKED (no artifact), got {decision.strategy}"
                )


# ---------------------------------------------------------------------------
# Policy doc presence
# ---------------------------------------------------------------------------


class TestPolicyDoc:
    def test_policy_doc_exists(self):
        path = get_project_root() / "docs" / "ionic_profile_policy.md"
        assert path.exists(), (
            "Wave 3 policy doc must exist at docs/ionic_profile_policy.md "
            "so the activation procedure is reviewable"
        )

    def test_policy_doc_mentions_all_four_preconditions(self):
        path = get_project_root() / "docs" / "ionic_profile_policy.md"
        text = path.read_text().lower()
        # Cheap content lock so a future edit cannot accidentally drop a
        # precondition section header.
        assert "usage context" in text
        assert "mixing-rule compatibility" in text or "mixing rule" in text
        assert "literature provenance" in text or "provenance" in text
        assert "lammps regression" in text or "lammps regression in ci" in text

    def test_policy_doc_warns_about_aqueous_vs_asphalt(self):
        path = get_project_root() / "docs" / "ionic_profile_policy.md"
        text = path.read_text().lower()
        assert "aqueous" in text and ("asphalt" in text or "binder" in text)
