"""GAFF2: end-to-end organic artifact → topology → emitted LAMMPS data.

Closes the loop by:

1. Loading the Toluene curated artifact from
   ``data/forcefield_artifacts/organic_gaff2/Toluene.json``.
2. Building a real ``MolTopology`` whose atom set matches the
   artifact.
3. Applying the artifact via the dispatcher
   (``forcefield.organic_typing_executor.assign_organic``) just like
   the production build path does.
4. Running the resulting topology through ``MolTopologyBuilder``
   and verifying that the emitted ``SystemTopology`` carries the
   curated charges atom by atom.
5. Writing the LAMMPS .data file via ``TopologyBuilder.write_lammps_data``
   and re-parsing the Atoms section to confirm the charges survive
   the round trip.

If any of these steps drift, the high-accuracy organic path is
silently broken even though all the unit tests pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from builder.mol_types import MolAtom, MolBond, MolTopology  # noqa: E402
from forcefield.organic_curated_artifact import (  # noqa: E402
    clear_artifact_cache,
    load_artifact,
)
from forcefield.organic_typing_executor import (  # noqa: E402
    assign_organic,
)
from forcefield.topology import MolTopologyBuilder  # noqa: E402
from forcefield.topology import TopologyBuilder as FFTopologyBuilder  # noqa: E402
from forcefield.typing_router import TypingStrategy  # noqa: E402

GAFF2_ARTIFACT_LABEL = "organic_gaff2_artifact"

_TEST_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "forcefield_artifacts"


@pytest.fixture(autouse=True)
def _gaff2_fixture_dir(monkeypatch):
    """Redirect artifact loading to test fixtures and clear cache."""
    clear_artifact_cache()

    def _mock_get_artifact_directory(ff_family: str = "organic_gaff2") -> Path:
        return _TEST_FIXTURE_DIR / ff_family

    monkeypatch.setattr(
        "forcefield.organic_curated_artifact.get_artifact_directory",
        _mock_get_artifact_directory,
    )
    yield
    clear_artifact_cache()


def _toluene_real_topology() -> MolTopology:
    """Build a real MolTopology that matches the Toluene artifact shape.

    The fixture has 15 atoms: 1 CT methyl C + 3 HC methyl H + 6 CA
    aromatic C (one of which is the ipso carbon at index 5) + 5 HA
    aromatic H. Bonds wire the methyl group to the ring and complete
    the aromatic ring + each ring H.
    """
    elements = [
        ("C", "methyl_C"),
        ("H", "methyl_H1"),
        ("H", "methyl_H2"),
        ("H", "methyl_H3"),
        ("C", "ring_ipso"),
        ("C", "ring_C2"),
        ("C", "ring_C3"),
        ("C", "ring_C4"),
        ("C", "ring_C5"),
        ("C", "ring_C6"),
        ("H", "ring_H2"),
        ("H", "ring_H3"),
        ("H", "ring_H4"),
        ("H", "ring_H5"),
        ("H", "ring_H6"),
    ]

    atoms = []
    for i, (element, _label) in enumerate(elements, start=1):
        atoms.append(
            MolAtom(
                index=i,
                x=float(i) * 0.1,
                y=0.0,
                z=0.0,
                element=element,
                ff_type="",  # filled in by the artifact
                charge=0.0,  # filled in by the artifact
                charge_defined=False,
            )
        )

    bonds = [
        # Methyl bonds
        MolBond(atom1=1, atom2=2, order=1),
        MolBond(atom1=1, atom2=3, order=1),
        MolBond(atom1=1, atom2=4, order=1),
        # Methyl to ring
        MolBond(atom1=1, atom2=5, order=1),
        # Aromatic ring (six-membered)
        MolBond(atom1=5, atom2=6, order=4),  # aromatic
        MolBond(atom1=6, atom2=7, order=4),
        MolBond(atom1=7, atom2=8, order=4),
        MolBond(atom1=8, atom2=9, order=4),
        MolBond(atom1=9, atom2=10, order=4),
        MolBond(atom1=10, atom2=5, order=4),
        # Ring H bonds
        MolBond(atom1=6, atom2=11, order=1),
        MolBond(atom1=7, atom2=12, order=1),
        MolBond(atom1=8, atom2=13, order=1),
        MolBond(atom1=9, atom2=14, order=1),
        MolBond(atom1=10, atom2=15, order=1),
    ]

    return MolTopology(mol_id="Toluene", atoms=atoms, bonds=bonds)


def _builder_from_assignment(result) -> MolTopologyBuilder:
    """Build a MolTopologyBuilder following the production calling convention.

    Mirrors ``builder.topology_helpers`` (artifact bonded_overrides →
    MolTopologyBuilder param overrides) so the curated artifact route's
    strict bonded coverage flows through exactly like production.
    """
    atom_overrides: dict = {}
    bond_overrides: dict = {}
    angle_overrides: dict = {}
    dihedral_overrides: dict = {}
    bo = result.bonded_overrides or {}
    for key, val in (bo.get("bond_types") or {}).items():
        bond_overrides[key] = {"k": val.k, "r0": val.r0}
    for key, val in (bo.get("angle_types") or {}).items():
        angle_overrides[key] = {"k": val.k, "theta0": val.theta0}
    for key, val in (bo.get("dihedral_types") or {}).items():
        dihedral_overrides[key] = {"style": val.style, "coeffs": val.coeffs}
    for key, val in (bo.get("atom_types") or {}).items():
        atom_overrides[key] = val
    return MolTopologyBuilder(
        ff_name="bulk_ff_gaff2",
        atom_param_overrides=atom_overrides or None,
        bond_param_overrides=bond_overrides or None,
        angle_param_overrides=angle_overrides or None,
        dihedral_param_overrides=dihedral_overrides or None,
    )


def _parse_lammps_data_charges(text: str) -> list[float]:
    """Re-extract per-atom charges from a LAMMPS data file written by us."""
    in_atoms = False
    charges: list[float] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Atoms"):
            in_atoms = True
            continue
        if not in_atoms:
            continue
        if not line:
            if charges:
                break
            continue
        if line.startswith("#"):
            continue
        # Stop at the next named section.
        first = line.split()[0]
        if first.isalpha():
            break
        parts = line.split()
        if len(parts) >= 7:
            try:
                charges.append(float(parts[3]))
            except (ValueError, IndexError):
                continue
    return charges


# ---------------------------------------------------------------------------
# Step 1+2+3: load artifact, build topology, dispatch
# ---------------------------------------------------------------------------


class TestArtifactDispatchEndToEnd:
    def test_dispatch_through_executor_applies_curated_charges(self, tmp_path):
        topology = _toluene_real_topology()
        result = assign_organic(
            topology=topology,
            mol_file=tmp_path / "Toluene.mol",
            strategy=TypingStrategy.ORGANIC_CURATED_ARTIFACT,
            source_id="Toluene",
        )

        # The dispatcher must surface the honest gaff2 artifact label.
        assert result.charge_model == GAFF2_ARTIFACT_LABEL
        assert result.artifact is not None
        assert result.artifact.mol_id == "Toluene"

        # Atom-by-atom check: every atom now carries the curated values.
        assert all(atom.charge_defined for atom in topology.atoms)
        # Methyl carbon (GAFF2: c3)
        assert topology.atoms[0].ff_type == "c3"
        assert topology.atoms[0].charge == pytest.approx(-0.0877, abs=1e-4)
        # Methyl hydrogens (GAFF2: hc)
        for idx in (1, 2, 3):
            assert topology.atoms[idx].ff_type == "hc"
            assert topology.atoms[idx].charge == pytest.approx(0.0442, abs=1e-4)
        # Ipso CA (GAFF2: ca)
        assert topology.atoms[4].ff_type == "ca"
        assert topology.atoms[4].charge == pytest.approx(-0.0587, abs=1e-4)
        # Five non-ipso ring CAs (GAFF2: ca)
        for idx in (5, 6, 7, 8, 9):
            assert topology.atoms[idx].ff_type == "ca"
        # Five aromatic HAs (GAFF2: ha)
        for idx in (10, 11, 12, 13, 14):
            assert topology.atoms[idx].ff_type == "ha"

    def test_neutrality_after_artifact_apply(self, tmp_path):
        topology = _toluene_real_topology()
        assign_organic(
            topology=topology,
            mol_file=tmp_path / "Toluene.mol",
            strategy=TypingStrategy.ORGANIC_CURATED_ARTIFACT,
            source_id="Toluene",
        )
        total = sum(atom.charge for atom in topology.atoms)
        assert total == pytest.approx(0.0, abs=5e-3), (
            f"Toluene artifact total charge {total:+.6f} not neutral; "
            "the artifact and the test topology have drifted."
        )


# ---------------------------------------------------------------------------
# Step 4: SystemTopology emission
# ---------------------------------------------------------------------------


class TestArtifactSystemTopologyEmission:
    """The MolTopologyBuilder must promote curated charges into SystemTopology atoms."""

    def test_system_topology_carries_curated_charges(self, tmp_path):
        topology = _toluene_real_topology()
        result = assign_organic(
            topology=topology,
            mol_file=tmp_path / "Toluene.mol",
            strategy=TypingStrategy.ORGANIC_CURATED_ARTIFACT,
            source_id="Toluene",
        )

        # Production convention: artifact bonded/atom overrides feed the
        # builder, and the curated route is strict (mol_strict=True).
        builder = _builder_from_assignment(result)
        system = builder.create_from_mol_topology(
            mol_topologies=[(topology, 1, True)],
            packed_coords=None,
            box_bounds=(0, 20, 0, 20, 0, 20),
        )

        # 15 atoms in the resulting SystemTopology
        assert len(system.atoms) == 15

        # Charges in SystemTopology must match the GAFF2 artifact
        atom_charges = [a.charge for a in system.atoms]
        # Methyl carbon (c3)
        assert atom_charges[0] == pytest.approx(-0.0877, abs=1e-4)
        # Ipso ca
        assert atom_charges[4] == pytest.approx(-0.0587, abs=1e-4)

        total = sum(atom_charges)
        assert total == pytest.approx(0.0, abs=5e-3)


# ---------------------------------------------------------------------------
# Step 5: LAMMPS data file round trip
# ---------------------------------------------------------------------------


class TestArtifactLammpsDataRoundTrip:
    """The full round trip: artifact → topology → builder → LAMMPS .data file."""

    def test_round_trip_preserves_curated_charges(self, tmp_path):
        topology = _toluene_real_topology()
        result = assign_organic(
            topology=topology,
            mol_file=tmp_path / "Toluene.mol",
            strategy=TypingStrategy.ORGANIC_CURATED_ARTIFACT,
            source_id="Toluene",
        )

        builder = _builder_from_assignment(result)
        system = builder.create_from_mol_topology(
            mol_topologies=[(topology, 1, True)],
            packed_coords=None,
            box_bounds=(0, 20, 0, 20, 0, 20),
        )

        out_path = tmp_path / "toluene.data"
        ff_writer = FFTopologyBuilder()
        ff_writer.write_lammps_data(system, out_path)
        assert out_path.exists()

        text = out_path.read_text()
        re_parsed = _parse_lammps_data_charges(text)
        assert len(re_parsed) == 15

        # GAFF2 AM1-BCC charges from fixture
        expected = [
            -0.0877,  # methyl C (c3)
            0.0442,
            0.0442,
            0.0442,  # methyl H (hc)
            -0.0587,  # ipso ca
            -0.1448,
            -0.1448,
            -0.1228,
            -0.1228,
            -0.1448,  # 5 ring CAs (ca)
            0.1365,
            0.1365,
            0.1395,
            0.1395,
            0.1418,  # 5 ring HAs (ha)
        ]
        for idx, (actual, want) in enumerate(zip(re_parsed, expected, strict=True)):
            assert actual == pytest.approx(want, abs=1e-3), (
                f"LAMMPS data round trip drift at atom #{idx + 1}: "
                f"emitted {actual} vs artifact {want}"
            )

        # Total charge survives the writer rounding too.
        assert sum(re_parsed) == pytest.approx(0.0, abs=5e-3)

    def test_emitted_data_file_declares_15_atoms(self, tmp_path):
        topology = _toluene_real_topology()
        result = assign_organic(
            topology=topology,
            mol_file=tmp_path / "Toluene.mol",
            strategy=TypingStrategy.ORGANIC_CURATED_ARTIFACT,
            source_id="Toluene",
        )

        builder = _builder_from_assignment(result)
        system = builder.create_from_mol_topology(
            mol_topologies=[(topology, 1, True)],
            packed_coords=None,
            box_bounds=(0, 20, 0, 20, 0, 20),
        )

        out_path = tmp_path / "toluene.data"
        FFTopologyBuilder().write_lammps_data(system, out_path)
        text = out_path.read_text()
        assert "15 atoms" in text


# ---------------------------------------------------------------------------
# Step 6: artifact and Wave 5 fixture stay consistent
# ---------------------------------------------------------------------------


class TestArtifactGaff2ConsistencyCheck:
    """GAFF2 artifact basic consistency check."""

    def test_toluene_artifact_loads(self):
        artifact = load_artifact("Toluene", ff_family="organic_gaff2")
        assert artifact is not None
        assert len(artifact.atoms) > 0
