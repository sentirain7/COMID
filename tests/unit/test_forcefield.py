"""
Unit tests for Force Field Module.

Tests cover: AtomType, BondType, SystemTopology,
ForceFieldRegistry, MolTopologyBuilder, and per-atom charge handling.

Phase 6: LigParGen, ParameterCache, and RDKit-based typing tests removed
(deleted modules).
"""

import pytest

from forcefield.topology import (
    AtomType,
    BondType,
    SystemTopology,
)


class TestAtomType:
    """Tests for AtomType."""

    def test_to_lammps_mass(self):
        """Test LAMMPS mass line generation."""
        at = AtomType(
            type_id=1,
            mass=12.011,
            element="C",
            comment="carbon",
        )

        line = at.to_lammps_mass()
        assert "1" in line
        assert "12.011" in line

    def test_to_lammps_pair(self):
        """Test LAMMPS pair coefficient generation."""
        at = AtomType(
            type_id=1,
            mass=12.011,
            element="C",
            epsilon=0.066,
            sigma=3.5,
        )

        line = at.to_lammps_pair()
        assert "0.066" in line or "0.0660" in line
        assert "3.5" in line


class TestBondType:
    """Tests for BondType."""

    def test_to_lammps(self):
        """Test LAMMPS bond coefficient generation."""
        bt = BondType(
            type_id=1,
            k=340.0,
            r0=1.09,
            comment="C-H",
        )

        line = bt.to_lammps()
        assert "1" in line
        assert "340" in line
        assert "1.09" in line


class TestSystemTopology:
    """Tests for SystemTopology."""

    def test_get_counts(self):
        """Test getting topology counts."""
        topo = SystemTopology()
        topo.atom_types = [AtomType(1, 12.0, "C"), AtomType(2, 1.0, "H")]
        topo.bond_types = [BondType(1, 340.0, 1.09)]

        counts = topo.get_counts()

        assert counts["atom_types"] == 2
        assert counts["bond_types"] == 1
        assert counts["atoms"] == 0


# =============================================================================
# ForceFieldRegistry Tests
# =============================================================================


class TestForceFieldRegistry:
    """Tests for ForceFieldRegistry (SSOT for force field parameters)."""

    def test_load_from_yaml(self):
        """Test loading registry from YAML file."""
        from pathlib import Path

        from contracts.policies.forcefield import ForceFieldRegistry

        # Get the registry path
        project_root = Path(__file__).parent.parent.parent
        registry_path = project_root / "data" / "forcefields" / "registry.yaml"

        registry = ForceFieldRegistry(registry_path)

        assert len(registry) >= 1
        assert "gaff2" in registry or "bulk_ff_gaff2" in registry

    def test_get_force_field(self):
        """Test getting a specific force field."""
        from contracts.policies.forcefield import get_default_ff_registry

        registry = get_default_ff_registry()
        ff = registry.get("bulk_ff_gaff2")

        assert ff is not None
        assert ff.name == "GAFF2"
        assert ff.pair_style == "lj/cut/coul/long"
        assert ff.pair_cutoff == 12.0

    def test_gaff2_runtime_profile(self):
        """Test GAFF2 runtime FF profile (no registry atom types needed)."""
        from contracts.policies.forcefield import get_default_ff_registry

        registry = get_default_ff_registry()
        ff = registry.get("bulk_ff_gaff2")

        assert ff is not None
        assert ff.dihedral_style == "fourier"
        assert ff.improper_style == "cvff"
        assert ff.native_mixing_rule == "arithmetic"
        assert ff.artifact_family == "organic_gaff2"

    def test_element_fallback_disabled_under_fail_closed_policy(self):
        """Fail-closed policy (v00.99.29): bulk_ff_gaff2 has no element_fallbacks.

        Previously this test asserted UFF-style fallbacks for additive elements
        like Al/Si/P.  The fail-closed transition removed element_fallback_source
        from registry.yaml so all LJ params must come from explicit per-molecule
        artifacts.  This test now verifies the policy invariant: registry-level
        ``get_atom_params`` returns ``None`` for additive-only elements.
        """
        from contracts.policies.forcefield import get_default_ff_registry

        registry = get_default_ff_registry()
        gaff2 = registry.get("bulk_ff_gaff2")

        assert gaff2 is not None
        # Fail-closed: registry no longer provides UFF-style fallbacks
        assert gaff2.element_fallbacks == {}, (
            "bulk_ff_gaff2.element_fallbacks must remain empty (fail-closed policy v00.99.29)"
        )
        for element in ("Al", "Si", "P"):
            assert gaff2.get_atom_params(element) is None, (
                f"Element {element!r} resolution must fail-closed at registry level; "
                "atom_types come from per-molecule artifacts (antechamber)."
            )

    def test_gaff2_registry_has_no_bonded_params(self):
        """GAFF2 bonded params come from per-molecule artifacts, not registry."""
        from contracts.policies.forcefield import get_default_ff_registry

        registry = get_default_ff_registry()
        ff = registry.get("bulk_ff_gaff2")

        assert ff is not None
        # GAFF2 registry has no bond/angle/dihedral params; those are in artifacts
        assert len(ff.bond_types) == 0
        assert len(ff.angle_types) == 0
        assert len(ff.dihedral_types) == 0

    def test_list_available(self):
        """Test listing available force fields."""
        from contracts.policies.forcefield import get_default_ff_registry

        registry = get_default_ff_registry()
        available = registry.list_available()

        assert len(available) >= 1
        assert any(ff["name"] == "GAFF2" for ff in available)

        # Check required fields
        for ff in available:
            assert "name" in ff
            assert "version" in ff
            assert "description" in ff

    def test_is_available(self):
        """Test checking force field availability."""
        from contracts.policies.forcefield import get_default_ff_registry

        registry = get_default_ff_registry()

        assert registry.is_available("bulk_ff_gaff2")
        assert not registry.is_available("nonexistent_ff")

    def test_get_default(self):
        """Test getting default force field."""
        from contracts.policies.forcefield import get_default_ff_registry

        registry = get_default_ff_registry()
        default_ff = registry.get_default()

        assert default_ff is not None
        # Default should be GAFF2 as defined in registry.yaml
        assert default_ff.name == "GAFF2"

    def test_bond_params_reversed_key_returns_none_for_gaff2(self):
        """GAFF2 registry has no bond_coeffs; lookup returns None."""
        from contracts.policies.forcefield import get_default_ff_registry

        registry = get_default_ff_registry()
        ff = registry.get("bulk_ff_gaff2")

        # GAFF2 bonded params come from per-molecule artifacts, not registry
        assert ff.get_bond_params("CT-HC") is None
        assert ff.get_bond_params("HC-CT") is None

    def test_force_field_to_dict(self):
        """Test force field serialization."""
        from contracts.policies.forcefield import get_default_ff_registry

        registry = get_default_ff_registry()
        ff = registry.get("bulk_ff_gaff2")

        d = ff.to_dict()

        assert d["name"] == "GAFF2"
        assert d["enabled"] is True


class TestMolTopologyBuilderWithRegistry:
    """Tests for MolTopologyBuilder using ForceFieldRegistry."""

    def test_init_with_default_ff(self):
        """Test initialization with default force field."""
        from forcefield.topology import MolTopologyBuilder

        builder = MolTopologyBuilder()

        assert builder.ff_config is not None
        assert builder.ff_config.name == "GAFF2"

    def test_init_with_specific_ff(self):
        """Test initialization with specific force field."""
        from forcefield.topology import MolTopologyBuilder

        builder = MolTopologyBuilder(ff_name="bulk_ff_gaff2")

        assert builder.ff_config is not None
        assert builder.ff_config.name == "GAFF2"

    def test_init_with_invalid_ff_falls_back(self):
        """Test initialization with invalid force field falls back to default."""
        from forcefield.topology import MolTopologyBuilder

        builder = MolTopologyBuilder(ff_name="nonexistent_ff")

        # Should fall back to default
        assert builder.ff_config is not None

    def test_get_ff_atom_params_with_artifact_atom_types(self, monkeypatch):
        """Builder resolves atom params when artifact-derived atom_types are injected.

        Production receives atom_types from per-molecule antechamber artifacts.
        This test mocks that injection (see ``tests/unit/_helpers/ff_mock.py``)
        and verifies the resolution path.  The fail-closed default (empty
        registry atom_types) is restored automatically by ``monkeypatch``.
        """
        from forcefield.topology import MolTopologyBuilder
        from tests.unit._helpers.ff_mock import patch_gaff2_atom_types

        patch_gaff2_atom_types(monkeypatch)

        builder = MolTopologyBuilder()
        params = builder._get_ff_atom_params("C", is_aromatic=False)
        assert params["mass"] == 12.011
        assert params["epsilon"] > 0

        aromatic_params = builder._get_ff_atom_params("C", is_aromatic=True)
        assert aromatic_params["epsilon"] > 0

    def test_unknown_element_raises_under_fail_closed_policy(self):
        """Without artifact atom_types, unknown elements must raise ValueError.

        Previously this test asserted Si had a UFF-style element fallback.
        Fail-closed policy (v00.99.29) removed that fallback so registry-only
        resolution of additive elements raises ``ValueError`` — the production
        code path requires antechamber artifact injection.
        """
        from forcefield.topology import MolTopologyBuilder

        builder = MolTopologyBuilder(ff_name="bulk_ff_gaff2")
        with pytest.raises(ValueError, match="(Unable to infer ff_type|is not defined in)"):
            builder._get_ff_atom_params("Si")

    def test_explicit_ff_type_resolves_with_artifact_atom_types(self, monkeypatch):
        """Explicit ff_type ('CT', 'HC') falls back to element when artifact atom_types are injected.

        GAFF2 registry never carries atom-type-level (CT/HC) entries, only
        element-level (C/H) artifact-derived params.  The builder should fall
        back from ff_type to element and emit a "GAFF2 C" / "GAFF2 H" comment.
        """
        from builder.molecule_db import MolAtom, MolBond, MolTopology
        from forcefield.topology import MolTopologyBuilder
        from tests.unit._helpers.ff_mock import patch_gaff2_atom_types

        patch_gaff2_atom_types(monkeypatch)

        mol_topo = MolTopology(
            mol_id="typed_methane_fragment",
            atoms=[
                MolAtom(
                    index=1,
                    x=0.0,
                    y=0.0,
                    z=0.0,
                    element="C",
                    ff_type="CT",
                    charge=-0.18,
                    charge_defined=True,
                ),
                MolAtom(
                    index=2,
                    x=1.1,
                    y=0.0,
                    z=0.0,
                    element="H",
                    ff_type="HC",
                    charge=0.18,
                    charge_defined=True,
                ),
            ],
            bonds=[MolBond(atom1=1, atom2=2, order=1)],
        )

        builder = MolTopologyBuilder(ff_name="bulk_ff_gaff2")
        system = builder.create_from_mol_topology([(mol_topo, 1)], box_bounds=(0, 10, 0, 10, 0, 10))

        comments = {atom_type.comment for atom_type in system.atom_types}
        assert "GAFF2 C" in comments
        assert "GAFF2 H" in comments

    def test_strict_param_coverage_raises_on_missing_bond_parameters(self, monkeypatch):
        """Strict mode should fail with 'Missing bond parameters' once atom resolution succeeds.

        Atom resolution is gated by artifact-derived atom_types (Cl/F mocked here)
        so the test reaches the strict bond-coverage check, which is the original
        intent of this test.
        """
        from builder.molecule_db import MolAtom, MolBond, MolTopology
        from forcefield.topology import MolTopologyBuilder
        from tests.unit._helpers.ff_mock import patch_gaff2_atom_types

        patch_gaff2_atom_types(monkeypatch)

        mol_topo = MolTopology(
            mol_id="cl_f",
            atoms=[
                MolAtom(
                    index=1,
                    x=0.0,
                    y=0.0,
                    z=0.0,
                    element="Cl",
                    charge=-0.1,
                    charge_defined=True,
                ),
                MolAtom(
                    index=2,
                    x=1.6,
                    y=0.0,
                    z=0.0,
                    element="F",
                    charge=0.1,
                    charge_defined=True,
                ),
            ],
            bonds=[MolBond(atom1=1, atom2=2, order=1)],
        )

        builder = MolTopologyBuilder(ff_name="bulk_ff_gaff2", strict_param_coverage=True)
        with pytest.raises(ValueError, match="Missing bond parameters"):
            builder.create_from_mol_topology([(mol_topo, 1)], box_bounds=(0, 10, 0, 10, 0, 10))


# =============================================================================
# Charge Handling Tests
# =============================================================================


class TestChargeHandling:
    """Tests for charge handling in topology builder."""

    def test_total_charge_sums_to_zero_for_neutral_molecule(self):
        """Test that charges sum to approximately zero for neutral molecules."""
        # GAFF2 AM1-BCC charges for hexadecane should sum to 0
        # CH3: -0.18 + 3*0.06 = 0
        # CH2: -0.12 + 2*0.06 = 0
        hexadecane_charges = (
            [-0.18, 0.06, 0.06, 0.06]  # Terminal CH3
            + [-0.12, 0.06, 0.06] * 14  # 14 CH2 groups
            + [-0.18, 0.06, 0.06, 0.06]  # Terminal CH3
        )

        total = sum(hexadecane_charges)
        assert abs(total) < 0.01, f"Total charge should be ~0, got {total}"

    def test_mol_topology_builder_uses_atom_charge_when_available(self, monkeypatch):
        """Test that MolTopologyBuilder uses atom.charge when defined.

        Requires artifact-derived atom_types (mocked) so atom resolution
        succeeds before the charge check is reached.
        """
        from builder.molecule_db import MolAtom, MolBond, MolTopology
        from forcefield.topology import MolTopologyBuilder
        from tests.unit._helpers.ff_mock import patch_gaff2_atom_types

        patch_gaff2_atom_types(monkeypatch)

        # Create atom with pre-set charge
        atoms = [
            MolAtom(
                index=1, x=0, y=0, z=0, element="C", charge=-0.18, charge_defined=True
            ),  # CH3 carbon
            MolAtom(index=2, x=1, y=0, z=0, element="H", charge=0.06, charge_defined=True),
        ]
        bonds = [MolBond(atom1=1, atom2=2, order=1)]
        mol_topo = MolTopology(mol_id="test_mol", atoms=atoms, bonds=bonds)

        builder = MolTopologyBuilder()
        system = builder.create_from_mol_topology(
            [(mol_topo, 1)],
            box_bounds=(0, 10, 0, 10, 0, 10),
        )

        # Verify charges in system are from atoms, not FF registry defaults
        assert len(system.atoms) == 2
        assert system.atoms[0].charge == pytest.approx(-0.18, abs=0.01)
        assert system.atoms[1].charge == pytest.approx(0.06, abs=0.01)

    def test_mol_topology_builder_rejects_undefined_charge(self, monkeypatch):
        """Builder must reject atoms without explicit per-atom charges.

        Requires artifact-derived atom_types (mocked) so atom resolution
        succeeds before the charge-defined check is reached.
        """
        from builder.molecule_db import MolAtom, MolBond, MolTopology
        from forcefield.topology import MolTopologyBuilder
        from tests.unit._helpers.ff_mock import patch_gaff2_atom_types

        patch_gaff2_atom_types(monkeypatch)

        # Atoms have numeric charge placeholders but no explicit charge definition.
        atoms = [
            MolAtom(index=1, x=0, y=0, z=0, element="C", charge=0.0),
            MolAtom(index=2, x=1, y=0, z=0, element="H", charge=0.0),
        ]
        bonds = [MolBond(atom1=1, atom2=2, order=1)]
        mol_topo = MolTopology(mol_id="test_mol", atoms=atoms, bonds=bonds)

        builder = MolTopologyBuilder()
        with pytest.raises(ValueError, match="Charge undefined"):
            builder.create_from_mol_topology(
                [(mol_topo, 1)],
                box_bounds=(0, 10, 0, 10, 0, 10),
            )
