"""Route-aware strict policy regression for MolTopologyBuilder.

The contract is:

* ``organic_curated_artifact`` and ``inorganic_profile`` molecules are STRICT
  -- any missing bonded coverage raises ``ValueError`` immediately so the
  curated path cannot silently ship default-fallback parameters.
* Non-strict molecules get the lax fallback.

These tests exercise ``MolTopologyBuilder._resolve_strict_lookup`` directly
because going through the full ``create_from_mol_topology`` pipeline would
require a real registered force field. The lookup helper is the unit of
behavior the plan locks in.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from forcefield.topology import MolTopologyBuilder  # noqa: E402


def _make_builder(*, global_strict: bool = False) -> MolTopologyBuilder:
    return MolTopologyBuilder(
        ff_name="bulk_ff_gaff2",
        strict_param_coverage=global_strict,
    )


class TestResolveStrictLookup:
    """``_resolve_strict_lookup`` is the per-build per-type strict gate."""

    def test_default_is_lax(self):
        builder = _make_builder()
        assert builder._resolve_strict_lookup(("CT", "HC")) is False

    def test_global_flag_makes_everything_strict(self):
        builder = _make_builder(global_strict=True)
        assert builder._resolve_strict_lookup(("CT", "HC")) is True
        assert builder._resolve_strict_lookup(("Si_tet", "O_br")) is True

    def test_strict_ff_type_propagates_to_lookups_using_it(self):
        """If a strict molecule registered ff_type 'Si_tet', any bond key
        touching 'Si_tet' must be strict — even if the *other* side of the
        bond came from a lax legacy molecule."""
        builder = _make_builder()
        builder._strict_ff_types = {"Si_tet"}
        assert builder._resolve_strict_lookup(("Si_tet", "O_br")) is True
        assert builder._resolve_strict_lookup(("CT", "Si_tet")) is True
        # Lookup that doesn't touch the strict type stays lax
        assert builder._resolve_strict_lookup(("CT", "HC")) is False

    def test_empty_strict_set_is_lax(self):
        builder = _make_builder()
        builder._strict_ff_types = set()
        assert builder._resolve_strict_lookup(("CT", "CA", "HA")) is False


class TestBondLookupRespectsStrict:
    """Missing bond params: lax → default fallback, strict → raise."""

    def test_missing_bond_lax_returns_default(self):
        builder = _make_builder()
        # _bond_params has no entry for ("ZZ", "QQ"); element fallback also missing
        params, label = builder._get_bond_interaction_params(
            type_key=("ZZ", "QQ"),
            element_key=("Zz", "Qq"),
        )
        assert params["k"] == 300.0
        assert params["r0"] == 1.5
        assert "default" in label

    def test_missing_bond_strict_raises(self):
        builder = _make_builder()
        builder._strict_ff_types = {"ZZ"}
        try:
            builder._get_bond_interaction_params(
                type_key=("ZZ", "QQ"),
                element_key=("Zz", "Qq"),
            )
        except ValueError as exc:
            assert "Missing bond parameters" in str(exc)
            assert "Wave 1" in str(exc)
            return
        raise AssertionError("Expected ValueError for missing bond in strict mode")


class TestAngleLookupRespectsStrict:
    def test_missing_angle_lax_returns_default(self):
        builder = _make_builder()
        params, label = builder._get_angle_interaction_params(
            type_key=("ZZ", "QQ", "RR"),
            element_key=("Zz", "Qq", "Rr"),
        )
        assert params["k"] == 50.0
        assert params["theta0"] == 109.5
        assert "default" in label

    def test_missing_angle_strict_raises(self):
        builder = _make_builder()
        builder._strict_ff_types = {"QQ"}
        try:
            builder._get_angle_interaction_params(
                type_key=("ZZ", "QQ", "RR"),
                element_key=("Zz", "Qq", "Rr"),
            )
        except ValueError as exc:
            assert "Missing angle parameters" in str(exc)
            return
        raise AssertionError("Expected ValueError for missing angle in strict mode")


class TestDihedralLookupRespectsStrict:
    def test_missing_dihedral_lax_returns_default(self):
        builder = _make_builder()
        params, label = builder._get_dihedral_interaction_params(
            type_key=("ZZ", "QQ", "RR", "SS"),
            element_key=("Zz", "Qq", "Rr", "Ss"),
        )
        assert params == {"style": "fourier", "coeffs": (0.0, 1, 1)}
        assert "default" in label

    def test_missing_dihedral_strict_raises(self):
        builder = _make_builder()
        builder._strict_ff_types = {"RR"}
        try:
            builder._get_dihedral_interaction_params(
                type_key=("ZZ", "QQ", "RR", "SS"),
                element_key=("Zz", "Qq", "Rr", "Ss"),
            )
        except ValueError as exc:
            assert "Missing dihedral parameters" in str(exc)
            return
        raise AssertionError("Expected ValueError for missing dihedral in strict mode")

    def test_inorganic_default_fallback_still_allowed_under_strict(self):
        """When dihedral_fallback_policy='allow_default_fallback' and the
        dihedral involves an inorganic ff_type, the silent default is still
        permitted — this is the explicit silica/CLAYFF carve-out and must
        not be re-broken by Wave 1's strict promotion."""
        builder = MolTopologyBuilder(
            ff_name="bulk_ff_gaff2",
            dihedral_fallback_policy="allow_default_fallback",
            inorganic_ff_types={"Si_tet", "O_br"},
        )
        builder._strict_ff_types = {"Si_tet"}
        params, label = builder._get_dihedral_interaction_params(
            type_key=("Si_tet", "O_br", "Si_tet", "O_br"),
            element_key=("Si", "O", "Si", "O"),
        )
        assert params == {"style": "fourier", "coeffs": (0.0, 1, 1)}
        assert "inorganic-default" in label


class TestCreateFromMolTopologyAcceptsStrictTuple:
    """Backward compatibility: accept both (mol, count) and (mol, count, strict)."""

    def test_legacy_two_tuple_form_resets_strict_set(self):
        builder = _make_builder()
        # Pre-seed a strict set, then call create_from_mol_topology with no
        # mol entries — the per-build reset MUST clear it.
        builder._strict_ff_types = {"PreSeeded"}
        system = builder.create_from_mol_topology(
            mol_topologies=[],
            packed_coords=None,
            box_bounds=(0, 10, 0, 10, 0, 10),
        )
        assert builder._strict_ff_types == set()
        assert system.atoms == []

    def test_three_tuple_form_marks_ff_types_strict(self):
        """Strict-flagged molecules contribute their ff_types to the set."""
        from builder.mol_types import MolAtom, MolTopology

        topo = MolTopology(
            mol_id="art_test",
            atoms=[
                MolAtom(
                    index=1,
                    x=0.0,
                    y=0.0,
                    z=0.0,
                    element="C",
                    ff_type="CT",
                    charge=-0.06,
                    charge_defined=True,
                ),
                MolAtom(
                    index=2,
                    x=1.1,
                    y=0.0,
                    z=0.0,
                    element="H",
                    ff_type="HC",
                    charge=0.06,
                    charge_defined=True,
                ),
            ],
            bonds=[],
        )
        # Provide atom LJ overrides so strict gate doesn't block the build
        builder = MolTopologyBuilder(
            ff_name="bulk_ff_gaff2",
            atom_param_overrides={
                "CT": {"mass": 12.011, "epsilon": 0.066, "sigma": 3.5, "charge": 0.0},
                "HC": {"mass": 1.008, "epsilon": 0.03, "sigma": 2.5, "charge": 0.0},
            },
        )
        builder.create_from_mol_topology(
            mol_topologies=[(topo, 1, True)],
            packed_coords=None,
            box_bounds=(0, 10, 0, 10, 0, 10),
        )
        # The strict set should now include the ff_types this molecule introduced.
        assert "CT" in builder._strict_ff_types
        assert "HC" in builder._strict_ff_types
