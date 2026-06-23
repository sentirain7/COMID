"""Regression tests for artifact bonded parameter passthrough (v00.99.05).

Ensures that curated artifact ff_types (e.g. c3, hc) and their bonded
overrides flow through ``MolTopologyBuilder`` without being downgraded
to element-level fallbacks.

Root cause: E2003 "Missing bond parameters for C-C" when strict curated
route ff_types were resolved to element symbols and artifact bonded
overrides were never passed to the builder.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from builder.mol_types import MolAtom, MolBond, MolTopology  # noqa: E402
from forcefield.topology import MolTopologyBuilder  # noqa: E402


def _make_builder(**kwargs) -> MolTopologyBuilder:
    defaults = {"ff_name": "bulk_ff_gaff2"}
    defaults.update(kwargs)
    return MolTopologyBuilder(**defaults)


# ---------------------------------------------------------------------------
# 1. _resolve_atom_ff_type: strict curated route preserves artifact ff_type
# ---------------------------------------------------------------------------


class TestResolveAtomFfTypeStrict:
    """mol_strict=True must preserve artifact-set ff_types even when they
    are not registered in the GAFF2 element-level atom_params dict."""

    def test_strict_preserves_gaff2_type(self):
        """c3 (GAFF2 sp3 carbon) must survive when mol_strict=True."""
        builder = _make_builder()
        atom = MolAtom(
            index=1,
            x=0,
            y=0,
            z=0,
            element="C",
            ff_type="c3",
            charge=-0.06,
            charge_defined=True,
        )
        result = builder._resolve_atom_ff_type(atom, "C", False, mol_strict=True)
        assert result == "c3"

    def test_strict_preserves_hc_type(self):
        """hc (GAFF2 H on sp3 C) must survive when mol_strict=True."""
        builder = _make_builder()
        atom = MolAtom(
            index=1,
            x=0,
            y=0,
            z=0,
            element="H",
            ff_type="hc",
            charge=0.03,
            charge_defined=True,
        )
        result = builder._resolve_atom_ff_type(atom, "H", False, mol_strict=True)
        assert result == "hc"

    def test_non_strict_element_fallback_blocked_for_gaff2(self):
        """Without mol_strict, element fallback is blocked for GAFF2 organic.

        bulk_ff_gaff2 has no element-level atom params (fail-closed policy):
        all LJ must come from artifact overrides, so resolving an unknown
        GAFF2 type without overrides raises instead of silently downgrading
        to element-level (UFF-like) parameters.
        """
        builder = _make_builder()
        atom = MolAtom(
            index=1,
            x=0,
            y=0,
            z=0,
            element="C",
            ff_type="c3",
            charge=-0.06,
            charge_defined=True,
        )
        with pytest.raises(ValueError, match="is not available"):
            builder._resolve_atom_ff_type(atom, "C", False, mol_strict=False)

    def test_strict_preserves_aromatic_ca_type(self):
        """ca (GAFF2 aromatic C) must survive for future aromatic artifacts."""
        builder = _make_builder()
        atom = MolAtom(
            index=1,
            x=0,
            y=0,
            z=0,
            element="C",
            ff_type="ca",
            charge=-0.12,
            charge_defined=True,
        )
        result = builder._resolve_atom_ff_type(atom, "C", True, mol_strict=True)
        assert result == "ca"


# ---------------------------------------------------------------------------
# 2. Bond/angle/dihedral overrides resolve via GAFF2 type keys
# ---------------------------------------------------------------------------


class TestBondedOverrideResolve:
    """Artifact bonded overrides keyed by GAFF2 types (c3-c3) must be
    found by the builder when atoms keep their GAFF2 ff_types."""

    def test_bond_override_resolves_c3_c3(self):
        builder = _make_builder(
            bond_param_overrides={"c3-c3": {"k": 303.1, "r0": 1.535}},
        )
        params, label = builder._get_bond_interaction_params(
            type_key=("c3", "c3"),
            element_key=("C", "C"),
        )
        assert params["k"] == 303.1
        assert params["r0"] == 1.535
        assert label == "c3-c3"

    def test_bond_override_resolves_c3_hc(self):
        builder = _make_builder(
            bond_param_overrides={"c3-hc": {"k": 337.3, "r0": 1.092}},
        )
        params, label = builder._get_bond_interaction_params(
            type_key=("c3", "hc"),
            element_key=("C", "H"),
        )
        assert params["k"] == 337.3
        assert label == "c3-hc"

    def test_bond_override_resolves_reversed_key(self):
        """Override stored as 'c3-hc' must also resolve for ('hc', 'c3')."""
        builder = _make_builder(
            bond_param_overrides={"c3-hc": {"k": 337.3, "r0": 1.092}},
        )
        params, label = builder._get_bond_interaction_params(
            type_key=("hc", "c3"),
            element_key=("H", "C"),
        )
        assert params["k"] == 337.3

    def test_angle_override_resolves(self):
        builder = _make_builder(
            angle_param_overrides={"c3-c3-c3": {"k": 63.21, "theta0": 110.63}},
        )
        params, label = builder._get_angle_interaction_params(
            type_key=("c3", "c3", "c3"),
            element_key=("C", "C", "C"),
        )
        assert params["k"] == 63.21
        assert params["theta0"] == 110.63

    def test_dihedral_override_resolves(self):
        builder = _make_builder(
            dihedral_param_overrides={
                "c3-c3-c3-c3": {"style": "fourier", "coeffs": (0.18, 3, 0.0)},
            },
        )
        params, label = builder._get_dihedral_interaction_params(
            type_key=("c3", "c3", "c3", "c3"),
            element_key=("C", "C", "C", "C"),
        )
        assert params["style"] == "fourier"
        assert params["coeffs"] == (0.18, 3, 0.0)


# ---------------------------------------------------------------------------
# 3. End-to-end: strict molecule with artifact overrides builds without error
# ---------------------------------------------------------------------------


class TestStrictMolWithOverridesBuildsSuccessfully:
    """Simulate the fixed pipeline: artifact ff_types preserved + bonded
    overrides passed → create_from_mol_topology succeeds."""

    @pytest.fixture
    def squalane_like_topo(self):
        """Minimal 4-atom linear alkane topology mimicking Squalane artifact."""
        atoms = [
            MolAtom(
                index=1, x=0, y=0, z=0, element="C", ff_type="c3", charge=-0.06, charge_defined=True
            ),
            MolAtom(
                index=2,
                x=1.54,
                y=0,
                z=0,
                element="C",
                ff_type="c3",
                charge=-0.06,
                charge_defined=True,
            ),
            MolAtom(
                index=3,
                x=0,
                y=1.09,
                z=0,
                element="H",
                ff_type="hc",
                charge=0.03,
                charge_defined=True,
            ),
            MolAtom(
                index=4,
                x=1.54,
                y=1.09,
                z=0,
                element="H",
                ff_type="hc",
                charge=0.03,
                charge_defined=True,
            ),
        ]
        bonds = [
            MolBond(atom1=1, atom2=2, order=1),
            MolBond(atom1=1, atom2=3, order=1),
            MolBond(atom1=2, atom2=4, order=1),
        ]
        return MolTopology(mol_id="test_c2h2", atoms=atoms, bonds=bonds)

    def test_build_succeeds_with_overrides(self, squalane_like_topo):
        """With artifact overrides (bonded + LJ), strict build must complete."""
        builder = _make_builder(
            atom_param_overrides={
                "c3": {"mass": 12.011, "epsilon": 0.1094, "sigma": 3.3997, "charge": 0.0},
                "hc": {"mass": 1.008, "epsilon": 0.0157, "sigma": 2.6495, "charge": 0.0},
            },
            bond_param_overrides={
                "c3-c3": {"k": 303.1, "r0": 1.535},
                "c3-hc": {"k": 337.3, "r0": 1.092},
            },
            angle_param_overrides={
                "c3-c3-hc": {"k": 46.37, "theta0": 110.05},
                "hc-c3-hc": {"k": 39.18, "theta0": 108.35},
            },
            dihedral_param_overrides={
                "hc-c3-c3-hc": {"style": "fourier", "coeffs": (0.15, 3, 0.0)},
            },
        )
        system = builder.create_from_mol_topology(
            mol_topologies=[(squalane_like_topo, 1, True)],
            packed_coords=None,
            box_bounds=(0, 20, 0, 20, 0, 20),
        )
        assert len(system.atoms) == 4
        assert len(system.bonds) == 3
        # ff_types in strict set must be GAFF2 level, not element level
        assert "c3" in builder._strict_ff_types
        assert "hc" in builder._strict_ff_types
        assert "C" not in builder._strict_ff_types
        assert "H" not in builder._strict_ff_types

    def test_build_fails_without_overrides(self, squalane_like_topo):
        """Without overrides, strict GAFF2 types cause LJ/bond failure."""
        builder = _make_builder()
        with pytest.raises(ValueError, match="Missing atom LJ parameters|Missing bond parameters"):
            builder.create_from_mol_topology(
                mol_topologies=[(squalane_like_topo, 1, True)],
                packed_coords=None,
                box_bounds=(0, 20, 0, 20, 0, 20),
            )

    def test_non_strict_build_blocked_without_overrides(self, squalane_like_topo):
        """Non-strict path: GAFF2 organic blocks element fallback (fail-closed).

        bulk_ff_gaff2 carries no element-level atom params, so even a
        non-strict build cannot downgrade GAFF2 ff_types to element/UFF
        defaults — building without artifact overrides must fail.
        """
        builder = _make_builder()
        with pytest.raises(ValueError, match="is not available"):
            builder.create_from_mol_topology(
                mol_topologies=[(squalane_like_topo, 1, False)],
                packed_coords=None,
                box_bounds=(0, 20, 0, 20, 0, 20),
            )


# ---------------------------------------------------------------------------
# 4. Improper override passthrough
# ---------------------------------------------------------------------------


class TestImproperOverrideResolve:
    """improper_param_overrides must take priority over dihedral/default."""

    def test_improper_override_stored(self):
        """Improper override dict must be stored in builder."""
        builder = _make_builder(
            improper_param_overrides={
                "ca-ca-ca-ha": {"style": "cvff", "coeffs": (1.1, -1, 2)},
            },
        )
        assert "ca-ca-ca-ha" in builder._improper_param_overrides

    def test_improper_override_used_in_build(self):
        """End-to-end: improper override flows to ImproperType coeffs."""
        atoms = [
            MolAtom(
                index=i + 1,
                x=float(i),
                y=0,
                z=0,
                element="C",
                ff_type="ca",
                charge=0.0,
                charge_defined=True,
            )
            for i in range(4)
        ]
        bonds = [
            MolBond(atom1=1, atom2=2, order=1),
            MolBond(atom1=2, atom2=3, order=1),
        ]
        topo = MolTopology(mol_id="test_imp", atoms=atoms, bonds=bonds)
        topo.improper_instances = [(1, 2, 3, 4)]

        builder = _make_builder(
            atom_param_overrides={
                "ca": {"mass": 12.011, "epsilon": 0.086, "sigma": 3.40, "charge": 0.0},
            },
            bond_param_overrides={"ca-ca": {"k": 350.0, "r0": 1.40}},
            angle_param_overrides={"ca-ca-ca": {"k": 63.0, "theta0": 120.0}},
            improper_param_overrides={
                "ca-ca-ca-ca": {"style": "cvff", "coeffs": (10.5, -1, 2)},
            },
        )
        system = builder.create_from_mol_topology(
            mol_topologies=[(topo, 1, True)],
            packed_coords=None,
            box_bounds=(0, 20, 0, 20, 0, 20),
        )
        assert len(system.improper_types) == 1
        assert system.improper_types[0].coeffs == (10.5, -1, 2)
        assert "improper_override" in system.improper_types[0].comment

    def test_improper_default_when_no_override(self):
        """Without improper override, default cvff (1.1, -1, 2) is used."""
        atoms = [
            MolAtom(
                index=i + 1,
                x=float(i),
                y=0,
                z=0,
                element="C",
                ff_type="ca",
                charge=0.0,
                charge_defined=True,
            )
            for i in range(4)
        ]
        bonds = [MolBond(atom1=1, atom2=2, order=1)]
        topo = MolTopology(mol_id="test_def", atoms=atoms, bonds=bonds)
        topo.improper_instances = [(1, 2, 3, 4)]

        builder = _make_builder(
            atom_param_overrides={
                "ca": {"mass": 12.011, "epsilon": 0.086, "sigma": 3.40, "charge": 0.0},
            },
            bond_param_overrides={"ca-ca": {"k": 350.0, "r0": 1.40}},
            angle_param_overrides={"ca-ca-ca": {"k": 63.0, "theta0": 120.0}},
        )
        system = builder.create_from_mol_topology(
            mol_topologies=[(topo, 1, True)],
            packed_coords=None,
            box_bounds=(0, 20, 0, 20, 0, 20),
        )
        assert len(system.improper_types) == 1
        assert system.improper_types[0].coeffs == (1.1, -1, 2)
        assert "default" in system.improper_types[0].comment
