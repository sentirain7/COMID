"""Unit tests for layered structure orientation handling."""

import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from builder.crystal_builder import CrystalBuilder
from builder.layer_spec import CrystalMaterial, CrystalSpec
from contracts.schemas import LayerSourceType
from features.layered_structures.service import (
    _collect_layered_ced_provenance,
    _combine_sources_to_geometry,
    _compute_crystal_grip_ranges,
    _protocol_layer_boundaries_with_vacuum,
    _ResolvedLayerSource,
    _validate_checks,
    _write_combined_lammps_data,
)
from parsers.data_parser import DataParser


def _write_minimal_data_file(
    path: Path,
    *,
    lx: float,
    ly: float,
    lz: float,
    element_mass: float = 12.011,
) -> None:
    lines = [
        "LAMMPS data file - test",
        "",
        "1 atoms",
        "0 bonds",
        "0 angles",
        "0 dihedrals",
        "0 impropers",
        "",
        "1 atom types",
        "0 bond types",
        "0 angle types",
        "0 dihedral types",
        "0 improper types",
        "",
        f"0.0 {lx:.6f} xlo xhi",
        f"0.0 {ly:.6f} ylo yhi",
        f"0.0 {lz:.6f} zlo zhi",
        "",
        "Masses",
        "",
        f"1 {element_mass:.4f}",
        "",
        "Atoms # full",
        "",
        f"1 1 1 0.0 {lx * 0.5:.6f} {ly * 0.5:.6f} {lz * 0.5:.6f}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_source(
    data_path: Path,
    *,
    source_type: LayerSourceType,
    source_id: str,
) -> _ResolvedLayerSource:
    parser = DataParser()
    info = parser.parse(data_path)
    type_map = parser.estimate_elements_from_info(info)
    xlo, xhi, ylo, yhi, zlo, zhi = info.box_bounds
    return _ResolvedLayerSource(
        source_type=source_type,
        source_id=source_id,
        name=source_id,
        status="ready",
        data_path=data_path,
        boundary_mode="ppp",
        info=info,
        type_map=type_map,
        box_size=(xhi - xlo, yhi - ylo, zhi - zlo),
    )


@pytest.fixture
def hydroxylated_crystal_source(tmp_path: Path) -> _ResolvedLayerSource:
    builder = CrystalBuilder()
    slab = builder.build(
        CrystalSpec(
            material=CrystalMaterial.SIO2,
            thickness_angstrom=16.0,
            xy_size_angstrom=20.0,
            hydroxylated=True,
        )
    )
    data_path = tmp_path / "crystal.data"
    slab.to_lammps_data(data_path)
    return _make_source(
        data_path,
        source_type=LayerSourceType.CRYSTAL_STRUCTURE,
        source_id="crys_test",
    )


@pytest.fixture
def binder_source(tmp_path: Path) -> _ResolvedLayerSource:
    data_path = tmp_path / "binder.data"
    _write_minimal_data_file(data_path, lx=20.0, ly=20.0, lz=12.0)
    return _make_source(
        data_path,
        source_type=LayerSourceType.BINDER_CELL,
        source_id="binder_test",
    )


def test_bottom_crystal_keeps_hydroxylated_face_upward(
    hydroxylated_crystal_source: _ResolvedLayerSource,
    binder_source: _ResolvedLayerSource,
) -> None:
    geometry = _combine_sources_to_geometry(
        [hydroxylated_crystal_source, binder_source],
        inter_layer_gap=0.0,
        per_layer_gaps=[0.0, None],
    )

    layer1_end = geometry.layer_boundaries_z[1]
    hydrogen_z = [
        atom.z for atom in geometry.atoms if atom.layer_index == 1 and atom.element == "H"
    ]

    assert hydrogen_z
    assert min(hydrogen_z) > layer1_end - 2.0


def test_upper_crystal_is_flipped_so_hydroxylated_face_points_downward(
    hydroxylated_crystal_source: _ResolvedLayerSource,
    binder_source: _ResolvedLayerSource,
) -> None:
    geometry = _combine_sources_to_geometry(
        [binder_source, hydroxylated_crystal_source],
        inter_layer_gap=0.0,
        per_layer_gaps=[0.0, None],
    )

    layer2_start = geometry.layer_boundaries_z[2]
    hydrogen_z = [
        atom.z for atom in geometry.atoms if atom.layer_index == 2 and atom.element == "H"
    ]

    assert hydrogen_z
    assert max(hydrogen_z) < layer2_start + 2.0


def test_validate_checks_warns_for_interior_crystal_dual_interface_limit(
    hydroxylated_crystal_source: _ResolvedLayerSource,
    binder_source: _ResolvedLayerSource,
) -> None:
    checks = _validate_checks(
        [binder_source, hydroxylated_crystal_source, binder_source],
        xy_tolerance_pct=10.0,
        min_xy_to_z_ratio=0.5,
    )

    orientation_check = next(
        check for check in checks if check.code == "crystal_interface_orientation"
    )
    limit_check = next(check for check in checks if check.code == "crystal_dual_interface_limit")

    assert orientation_check.status == "pass"
    assert orientation_check.details["flipped_layer_indices"] == [2]
    assert limit_check.status == "warn"
    assert limit_check.details["interior_crystal_layer_indices"] == [2]


def test_collect_layered_ced_provenance_aggregates_binder_source_mol_counts(monkeypatch) -> None:
    fake_exp = SimpleNamespace(
        comp_asphaltene_wt=20.0,
        comp_resin_wt=30.0,
        comp_aromatic_wt=35.0,
        comp_saturate_wt=15.0,
    )

    class _Repo:
        def __init__(self, _session):
            pass

        def get_by_id(self, exp_id):
            return fake_exp if exp_id in {"binder_A", "binder_B"} else None

        def get_experiment_molecules(self, exp_id):
            if exp_id == "binder_A":
                return [
                    (SimpleNamespace(count=3), SimpleNamespace(mol_id="mol_A")),
                    (SimpleNamespace(count=2), SimpleNamespace(mol_id="mol_B")),
                ]
            if exp_id == "binder_B":
                return [
                    (SimpleNamespace(count=4), SimpleNamespace(mol_id="mol_A")),
                ]
            return []

    @contextmanager
    def _stub_session_scope():
        yield object()

    import database.connection as _conn_mod
    import database.repositories as _repo_mod

    monkeypatch.setattr(_conn_mod, "session_scope", _stub_session_scope)
    monkeypatch.setattr(_repo_mod, "ExperimentRepository", _Repo)

    sources = [
        SimpleNamespace(source_type=LayerSourceType.BINDER_CELL, source_id="binder_A"),
        SimpleNamespace(source_type=LayerSourceType.BINDER_CELL, source_id="binder_B"),
        SimpleNamespace(source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="crystal_1"),
    ]

    comp, no_binder_source, mol_counts, records = _collect_layered_ced_provenance(sources)

    assert no_binder_source is False
    assert comp["asphaltene"] == pytest.approx(20.0)
    assert mol_counts == {"mol_A": 7, "mol_B": 2}
    assert [r["source_exp_id"] for r in records] == ["binder_A", "binder_B"]


# ---------------------------------------------------------------------------
# Helpers for multi-atom data files
# ---------------------------------------------------------------------------


def _write_binder_data_file(
    path: Path,
    *,
    lx: float = 20.0,
    ly: float = 20.0,
    lz: float = 12.0,
) -> None:
    """Write a binder-like data file with 2 atom types, 1 bond, and Pair Coeffs."""
    lines = [
        "LAMMPS data file - binder test",
        "",
        "3 atoms",
        "1 bonds",
        "0 angles",
        "0 dihedrals",
        "0 impropers",
        "",
        "2 atom types",
        "1 bond types",
        "0 angle types",
        "0 dihedral types",
        "0 improper types",
        "",
        f"0.0 {lx:.6f} xlo xhi",
        f"0.0 {ly:.6f} ylo yhi",
        f"0.0 {lz:.6f} zlo zhi",
        "",
        "Masses",
        "",
        "1 12.0110 # C",
        "2 1.0080 # H",
        "",
        "Pair Coeffs",
        "",
        "1 0.066 3.5000 # CT",
        "2 0.030 2.5000 # HC",
        "",
        "Bond Coeffs",
        "",
        "1 340.0 1.09",
        "",
        "Atoms # full",
        "",
        f"1 1 1 -0.18 {lx * 0.3:.6f} {ly * 0.5:.6f} {lz * 0.5:.6f}",
        f"2 1 2  0.06 {lx * 0.4:.6f} {ly * 0.5:.6f} {lz * 0.5:.6f}",
        f"3 2 1 -0.18 {lx * 0.6:.6f} {ly * 0.5:.6f} {lz * 0.5:.6f}",
        "",
        "Bonds",
        "",
        "1 1 1 2",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_crystal_data_file(
    path: Path,
    *,
    lx: float = 20.0,
    ly: float = 20.0,
    lz: float = 10.0,
) -> None:
    """Write a crystal-like data file: 2 atom types, no Pair Coeffs, no bonds."""
    lines = [
        "LAMMPS data file - crystal test",
        "",
        "2 atoms",
        "0 bonds",
        "0 angles",
        "0 dihedrals",
        "0 impropers",
        "",
        "2 atom types",
        "0 bond types",
        "0 angle types",
        "0 dihedral types",
        "0 improper types",
        "",
        f"0.0 {lx:.6f} xlo xhi",
        f"0.0 {ly:.6f} ylo yhi",
        f"0.0 {lz:.6f} zlo zhi",
        "",
        "Masses",
        "",
        "1 28.0850 # Si",
        "2 15.9990 # O",
        "",
        "Atoms # full",
        "",
        f"1 1 1 0.0 {lx * 0.3:.6f} {ly * 0.5:.6f} {lz * 0.3:.6f}",
        f"2 1 2 0.0 {lx * 0.6:.6f} {ly * 0.5:.6f} {lz * 0.6:.6f}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Finding 1: Crystal atom types must get INTERFACE FF / UFF Pair Coeffs
# ---------------------------------------------------------------------------


class TestInterfaceFFPairCoeffs:
    """Crystal types without Pair Coeffs must receive INTERFACE FF LJ parameters."""

    def test_crystal_types_get_interface_ff_pair_coeffs(self, tmp_path: Path) -> None:
        binder_path = tmp_path / "binder.data"
        crystal_path = tmp_path / "crystal.data"
        _write_binder_data_file(binder_path)
        _write_crystal_data_file(crystal_path)

        binder_src = _make_source(
            binder_path,
            source_type=LayerSourceType.BINDER_CELL,
            source_id="b1",
        )
        crystal_src = _make_source(
            crystal_path,
            source_type=LayerSourceType.CRYSTAL_STRUCTURE,
            source_id="c1",
        )

        sources = [crystal_src, binder_src]
        geometry = _combine_sources_to_geometry(sources, inter_layer_gap=2.0)
        out_path = tmp_path / "combined.data"
        _write_combined_lammps_data(out_path, geometry, sources=sources)

        content = out_path.read_text()

        # Must have Pair Coeffs section
        assert "Pair Coeffs" in content

        # Parse all Pair Coeff lines
        in_pair = False
        pair_type_ids: set[int] = set()
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped == "Pair Coeffs":
                in_pair = True
                continue
            if in_pair and stripped == "":
                continue
            if in_pair:
                # A new section header stops the pair coeffs block
                if stripped and not stripped[0].isdigit():
                    in_pair = False
                    continue
                parts = stripped.split()
                if parts and parts[0].isdigit():
                    pair_type_ids.add(int(parts[0]))

        # 4 total atom types: 2 crystal + 2 binder
        assert len(pair_type_ids) == 4
        # Crystal types (1,2 = Si,O) should have INTERFACE FF comment
        iff_lines = [ln for ln in content.split("\n") if "INTERFACE FF" in ln]
        assert len(iff_lines) >= 2  # Si and O (+ annotation comment)
        # No UFF fallback for Si and O (both covered by INTERFACE FF)
        uff_lines = [ln for ln in content.split("\n") if "UFF fallback" in ln]
        assert len(uff_lines) == 0

    def test_interface_ff_si_epsilon_much_smaller_than_uff(self, tmp_path: Path) -> None:
        """INTERFACE FF Si has epsilon ~0.0004, far less than UFF 0.402."""
        binder_path = tmp_path / "binder.data"
        crystal_path = tmp_path / "crystal.data"
        _write_binder_data_file(binder_path)
        _write_crystal_data_file(crystal_path)

        binder_src = _make_source(
            binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1"
        )
        crystal_src = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )

        sources = [crystal_src, binder_src]
        geometry = _combine_sources_to_geometry(sources, inter_layer_gap=2.0)
        out_path = tmp_path / "combined.data"
        _write_combined_lammps_data(out_path, geometry, sources=sources)

        content = out_path.read_text()
        # Find Si pair coeff line
        for line in content.split("\n"):
            if "INTERFACE FF (Si)" in line:
                parts = line.split()
                eps = float(parts[1])
                assert eps < 0.01  # IFF: 0.0004; UFF was 0.402
                break
        else:
            pytest.fail("INTERFACE FF (Si) pair coeff line not found")

    def test_crystal_ff_annotation_present(self, tmp_path: Path) -> None:
        """Data file must contain INTERFACE FF annotation for metadata tracking."""
        binder_path = tmp_path / "binder.data"
        crystal_path = tmp_path / "crystal.data"
        _write_binder_data_file(binder_path)
        _write_crystal_data_file(crystal_path)

        binder_src = _make_source(
            binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1"
        )
        crystal_src = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )

        sources = [crystal_src, binder_src]
        geometry = _combine_sources_to_geometry(sources, inter_layer_gap=2.0)
        out_path = tmp_path / "combined.data"
        _write_combined_lammps_data(out_path, geometry, sources=sources)

        content = out_path.read_text()
        assert "# Crystal FF: INTERFACE_FF" in content

    def test_all_binder_types_no_fallback_needed(self, tmp_path: Path) -> None:
        """When all layers have Pair Coeffs, no fallback lines appear."""
        b1 = tmp_path / "b1.data"
        b2 = tmp_path / "b2.data"
        _write_binder_data_file(b1, lz=10.0)
        _write_binder_data_file(b2, lz=10.0)

        s1 = _make_source(b1, source_type=LayerSourceType.BINDER_CELL, source_id="b1")
        s2 = _make_source(b2, source_type=LayerSourceType.BINDER_CELL, source_id="b2")

        sources = [s1, s2]
        geometry = _combine_sources_to_geometry(sources, inter_layer_gap=2.0)
        out_path = tmp_path / "combined.data"
        _write_combined_lammps_data(out_path, geometry, sources=sources)

        content = out_path.read_text()
        assert "UFF fallback" not in content
        assert "INTERFACE FF" not in content  # no crystal → no fallback at all

    def test_crystal_type_annotation_present(self, tmp_path: Path) -> None:
        binder_path = tmp_path / "binder.data"
        crystal_path = tmp_path / "crystal.data"
        _write_binder_data_file(binder_path)
        _write_crystal_data_file(crystal_path)

        binder_src = _make_source(
            binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1"
        )
        crystal_src = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )

        sources = [crystal_src, binder_src]
        geometry = _combine_sources_to_geometry(sources, inter_layer_gap=2.0)
        out_path = tmp_path / "combined.data"
        _write_combined_lammps_data(out_path, geometry, sources=sources)

        content = out_path.read_text()
        match = re.search(r"^# Crystal atom types:\s*(.+)$", content, flags=re.MULTILINE)
        assert match is not None
        crystal_types = {int(t) for t in match.group(1).split()}
        # Crystal is layer 0 (offset 0), has types 1,2
        assert crystal_types == {1, 2}


# ---------------------------------------------------------------------------
# Finding 2: Molecule IDs must be preserved with per-layer offsets
# ---------------------------------------------------------------------------


class TestMoleculeIdPreservation:
    """Atoms must keep their original molecule identity across layers."""

    def test_mol_ids_preserved_not_collapsed(self, tmp_path: Path) -> None:
        binder_path = tmp_path / "binder.data"
        crystal_path = tmp_path / "crystal.data"
        _write_binder_data_file(binder_path)
        _write_crystal_data_file(crystal_path)

        binder_src = _make_source(
            binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1"
        )
        crystal_src = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )

        # crystal first, then binder
        sources = [crystal_src, binder_src]
        geometry = _combine_sources_to_geometry(sources, inter_layer_gap=2.0)
        out_path = tmp_path / "combined.data"
        _write_combined_lammps_data(out_path, geometry, sources=sources)

        content = out_path.read_text()

        # Parse Atoms section
        in_atoms = False
        mol_ids: list[int] = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("Atoms"):
                in_atoms = True
                continue
            if in_atoms and stripped == "":
                continue
            if in_atoms:
                if stripped and not stripped[0].isdigit():
                    break
                parts = stripped.split()
                if len(parts) >= 7:
                    mol_ids.append(int(parts[1]))

        # Crystal has 2 atoms with mol_id=1 → global mol_ids 1
        # Binder has 3 atoms: mol_id 1 (atoms 1,2), mol_id 2 (atom 3)
        # After offset: binder mol_ids become 1+1=2, 1+1=2, 2+1=3
        assert len(mol_ids) == 5
        # Must NOT all be same value (that was the bug: all = layer_index)
        assert len(set(mol_ids)) > 1
        # Crystal atoms: mol_id 1 (original 1 + offset 0)
        assert mol_ids[0] == 1
        assert mol_ids[1] == 1
        # Binder atoms must have offset applied
        binder_mols = mol_ids[2:]
        assert max(binder_mols) > 1  # not all collapsed to layer_index

    def test_two_binder_layers_mol_ids_distinct(self, tmp_path: Path) -> None:
        """Two binder layers should have non-overlapping molecule IDs."""
        b1 = tmp_path / "b1.data"
        b2 = tmp_path / "b2.data"
        _write_binder_data_file(b1, lz=10.0)
        _write_binder_data_file(b2, lz=10.0)

        s1 = _make_source(b1, source_type=LayerSourceType.BINDER_CELL, source_id="b1")
        s2 = _make_source(b2, source_type=LayerSourceType.BINDER_CELL, source_id="b2")

        sources = [s1, s2]
        geometry = _combine_sources_to_geometry(sources, inter_layer_gap=2.0)
        out_path = tmp_path / "combined.data"
        _write_combined_lammps_data(out_path, geometry, sources=sources)

        content = out_path.read_text()

        in_atoms = False
        mol_ids: list[int] = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("Atoms"):
                in_atoms = True
                continue
            if in_atoms and stripped == "":
                continue
            if in_atoms:
                if stripped and not stripped[0].isdigit():
                    break
                parts = stripped.split()
                if len(parts) >= 7:
                    mol_ids.append(int(parts[1]))

        # Layer 1: 3 atoms, mol_ids 1,1,2 (offset=0)
        # Layer 2: 3 atoms, mol_ids 1+2=3, 1+2=3, 2+2=4 (offset=2)
        assert len(mol_ids) == 6
        layer1_mols = set(mol_ids[:3])
        layer2_mols = set(mol_ids[3:])
        # No overlap between layers
        assert layer1_mols.isdisjoint(layer2_mols)


# ---------------------------------------------------------------------------
# Affine rescaling: amorphous layers rescale XY to match crystal
# ---------------------------------------------------------------------------


class TestAffineRescaling:
    """Amorphous/binder layers are affine-rescaled to fill crystal XY box."""

    def test_binder_rescaled_to_crystal_xy(self, tmp_path: Path) -> None:
        """Binder with different XY gets rescaled, not just centered."""
        crystal_path = tmp_path / "crystal.data"
        binder_path = tmp_path / "binder.data"
        # Crystal: 48x48, binder: 50x50 — binder must shrink
        _write_crystal_data_file(crystal_path, lx=48.0, ly=48.0, lz=10.0)
        _write_binder_data_file(binder_path, lx=50.0, ly=50.0, lz=12.0)

        crystal_src = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )
        binder_src = _make_source(
            binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1"
        )

        geometry = _combine_sources_to_geometry([crystal_src, binder_src], inter_layer_gap=2.0)

        # Global box must be crystal XY (48x48), not binder (50x50)
        assert geometry.box_size[0] == pytest.approx(48.0, abs=0.01)
        assert geometry.box_size[1] == pytest.approx(48.0, abs=0.01)

        # Binder atoms (layer 2) must all lie within [0, 48]
        binder_atoms = [a for a in geometry.atoms if a.layer_index == 2]
        assert binder_atoms
        for atom in binder_atoms:
            assert 0.0 <= atom.x <= 48.0 + 0.01
            assert 0.0 <= atom.y <= 48.0 + 0.01

    def test_binder_expanded_to_crystal_xy(self, tmp_path: Path) -> None:
        """Binder smaller than crystal gets stretched to fill crystal XY."""
        crystal_path = tmp_path / "crystal.data"
        binder_path = tmp_path / "binder.data"
        # Crystal: 52x52, binder: 50x50 — binder must expand
        _write_crystal_data_file(crystal_path, lx=52.0, ly=52.0, lz=10.0)
        _write_binder_data_file(binder_path, lx=50.0, ly=50.0, lz=12.0)

        crystal_src = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )
        binder_src = _make_source(
            binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1"
        )

        geometry = _combine_sources_to_geometry([crystal_src, binder_src], inter_layer_gap=2.0)

        assert geometry.box_size[0] == pytest.approx(52.0, abs=0.01)
        assert geometry.box_size[1] == pytest.approx(52.0, abs=0.01)

        # Binder atoms should span close to full 52Å (scaled from 50Å)
        binder_atoms = [a for a in geometry.atoms if a.layer_index == 2]
        max_x = max(a.x for a in binder_atoms)
        # Original max x ~ 50*0.6 = 30.0, scaled ~ 30 * 52/50 = 31.2
        assert max_x > 30.0  # expanded beyond original

    def test_crystal_never_rescaled(self, tmp_path: Path) -> None:
        """Crystal layer must preserve exact lattice coordinates (centering only)."""
        crystal_path = tmp_path / "crystal.data"
        binder_path = tmp_path / "binder.data"
        # Crystal smaller than binder: crystal should be centered, not rescaled
        _write_crystal_data_file(crystal_path, lx=48.0, ly=48.0, lz=10.0)
        _write_binder_data_file(binder_path, lx=48.0, ly=48.0, lz=12.0)

        crystal_src = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )
        binder_src = _make_source(
            binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1"
        )

        geometry = _combine_sources_to_geometry([crystal_src, binder_src], inter_layer_gap=0.0)

        # Crystal atoms (layer 1): original x = 48*0.3 = 14.4, x = 48*0.6 = 28.8
        crystal_atoms = [a for a in geometry.atoms if a.layer_index == 1]
        xs = sorted(a.x for a in crystal_atoms)
        # With centering shift = 0 (crystal IS the reference), positions unchanged
        assert xs[0] == pytest.approx(48.0 * 0.3, abs=0.01)
        assert xs[1] == pytest.approx(48.0 * 0.6, abs=0.01)

    def test_binder_binder_no_rescale(self, tmp_path: Path) -> None:
        """When no crystal exists, equal-size binders don't get rescaled."""
        b1 = tmp_path / "b1.data"
        b2 = tmp_path / "b2.data"
        _write_binder_data_file(b1, lx=50.0, ly=50.0, lz=10.0)
        _write_binder_data_file(b2, lx=50.0, ly=50.0, lz=10.0)

        s1 = _make_source(b1, source_type=LayerSourceType.BINDER_CELL, source_id="b1")
        s2 = _make_source(b2, source_type=LayerSourceType.BINDER_CELL, source_id="b2")

        geometry = _combine_sources_to_geometry([s1, s2], inter_layer_gap=2.0)
        assert geometry.box_size[0] == pytest.approx(50.0, abs=0.01)
        assert geometry.box_size[1] == pytest.approx(50.0, abs=0.01)

    def test_asymmetric_rescale(self, tmp_path: Path) -> None:
        """Crystal with non-square XY: binder rescaled anisotropically."""
        crystal_path = tmp_path / "crystal.data"
        binder_path = tmp_path / "binder.data"
        # Crystal: 48x52 (non-square), binder: 50x50 (square)
        _write_crystal_data_file(crystal_path, lx=48.0, ly=52.0, lz=10.0)
        _write_binder_data_file(binder_path, lx=50.0, ly=50.0, lz=12.0)

        crystal_src = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )
        binder_src = _make_source(
            binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1"
        )

        geometry = _combine_sources_to_geometry([crystal_src, binder_src], inter_layer_gap=2.0)

        # Box must match crystal exactly
        assert geometry.box_size[0] == pytest.approx(48.0, abs=0.01)
        assert geometry.box_size[1] == pytest.approx(52.0, abs=0.01)

        # Binder atom x scaled by 48/50 = 0.96, y scaled by 52/50 = 1.04
        binder_atoms = [a for a in geometry.atoms if a.layer_index == 2]
        # Original atom at x=50*0.6=30 → rescaled to 30*48/50 = 28.8
        atom_at_06 = [a for a in binder_atoms if a.original_atom_type == 1]
        max_x_atom = max(atom_at_06, key=lambda a: a.x)
        assert max_x_atom.x == pytest.approx(30.0 * 48.0 / 50.0, abs=0.01)

    def test_topology_preserved_after_rescale(self, tmp_path: Path) -> None:
        """Bond connectivity must survive rescaling (only coords change)."""
        crystal_path = tmp_path / "crystal.data"
        binder_path = tmp_path / "binder.data"
        _write_crystal_data_file(crystal_path, lx=48.0, ly=48.0, lz=10.0)
        _write_binder_data_file(binder_path, lx=50.0, ly=50.0, lz=12.0)

        crystal_src = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )
        binder_src = _make_source(
            binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1"
        )

        geometry = _combine_sources_to_geometry([crystal_src, binder_src], inter_layer_gap=2.0)

        # Binder has 1 bond between its first two atoms (indices 2,3 after crystal)
        assert len(geometry.bonds) == 1
        bond = geometry.bonds[0]
        # Crystal has 2 atoms, binder starts at index 2
        assert bond == [2, 3]

    def test_multilayer_all_noncrstyal_rescaled_to_bottom_crystal(self, tmp_path: Path) -> None:
        """Crystal(48)-Binder(50)-Binder(51)-Amorphous(49)-Crystal(52):
        all 3 non-crystal layers rescaled to bottom crystal XY (48)."""
        c1_path = tmp_path / "c1.data"
        b1_path = tmp_path / "b1.data"
        b2_path = tmp_path / "b2.data"
        a1_path = tmp_path / "a1.data"
        c2_path = tmp_path / "c2.data"
        _write_crystal_data_file(c1_path, lx=48.0, ly=48.0, lz=10.0)
        _write_binder_data_file(b1_path, lx=50.0, ly=50.0, lz=12.0)
        _write_binder_data_file(b2_path, lx=51.0, ly=51.0, lz=12.0)
        _write_binder_data_file(a1_path, lx=49.0, ly=49.0, lz=8.0)
        _write_crystal_data_file(c2_path, lx=52.0, ly=52.0, lz=10.0)

        c1 = _make_source(c1_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1")
        b1 = _make_source(b1_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1")
        b2 = _make_source(b2_path, source_type=LayerSourceType.BINDER_CELL, source_id="b2")
        a1 = _make_source(
            a1_path, source_type=LayerSourceType.INTERFACE_MOLECULE_CELL, source_id="a1"
        )
        c2 = _make_source(c2_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c2")

        geometry = _combine_sources_to_geometry([c1, b1, b2, a1, c2], inter_layer_gap=2.0)

        # Box XY = bottom crystal (48), NOT max(48,52)=52
        assert geometry.box_size[0] == pytest.approx(48.0, abs=0.01)
        assert geometry.box_size[1] == pytest.approx(48.0, abs=0.01)

        # All binder/amorphous atoms must lie within [0, 48]
        for layer_i in (2, 3, 4):  # b1, b2, a1
            layer_atoms = [a for a in geometry.atoms if a.layer_index == layer_i]
            assert layer_atoms, f"Layer {layer_i} has no atoms"
            for atom in layer_atoms:
                assert 0.0 <= atom.x <= 48.0 + 0.01, (
                    f"Layer {layer_i} atom x={atom.x:.2f} outside [0,48]"
                )
                assert 0.0 <= atom.y <= 48.0 + 0.01, (
                    f"Layer {layer_i} atom y={atom.y:.2f} outside [0,48]"
                )

        # b1: original x=50*0.6=30 → rescaled 30*48/50=28.8
        b1_atoms = [a for a in geometry.atoms if a.layer_index == 2]
        b1_max_x = max(a.x for a in b1_atoms)
        assert b1_max_x == pytest.approx(30.0 * 48.0 / 50.0, abs=0.01)

        # b2: original x=51*0.6=30.6 → rescaled 30.6*48/51=28.8
        b2_atoms = [a for a in geometry.atoms if a.layer_index == 3]
        b2_max_x = max(a.x for a in b2_atoms)
        assert b2_max_x == pytest.approx(30.6 * 48.0 / 51.0, abs=0.01)

        # a1: original x=49*0.6=29.4 → rescaled 29.4*48/49≈28.8
        a1_atoms = [a for a in geometry.atoms if a.layer_index == 4]
        a1_max_x = max(a.x for a in a1_atoms)
        assert a1_max_x == pytest.approx(29.4 * 48.0 / 49.0, abs=0.05)

    def test_bottom_crystal_reference_not_max(self, tmp_path: Path) -> None:
        """When top crystal is larger, reference is still the bottom crystal."""
        c1_path = tmp_path / "c1.data"
        b1_path = tmp_path / "b1.data"
        c2_path = tmp_path / "c2.data"
        _write_crystal_data_file(c1_path, lx=48.0, ly=48.0, lz=10.0)
        _write_binder_data_file(b1_path, lx=50.0, ly=50.0, lz=12.0)
        _write_crystal_data_file(c2_path, lx=55.0, ly=55.0, lz=10.0)

        c1 = _make_source(c1_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1")
        b1 = _make_source(b1_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1")
        c2 = _make_source(c2_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c2")

        geometry = _combine_sources_to_geometry([c1, b1, c2], inter_layer_gap=2.0)

        # Must be 48 (bottom crystal), NOT 55 (top crystal max)
        assert geometry.box_size[0] == pytest.approx(48.0, abs=0.01)
        assert geometry.box_size[1] == pytest.approx(48.0, abs=0.01)

        # Binder rescaled to 48
        binder_atoms = [a for a in geometry.atoms if a.layer_index == 2]
        for atom in binder_atoms:
            assert 0.0 <= atom.x <= 48.0 + 0.01


# ---------------------------------------------------------------------------
# Validation: affine_rescale check in _validate_checks
# ---------------------------------------------------------------------------


class TestZVacuumBuffer:
    """Submit data file has z-vacuum; preview geometry does not."""

    def test_protocol_boundaries_shifted_by_vacuum(self) -> None:
        """Tensile grip boundaries must use the same z-offset as submit data."""
        from contracts.policies.layer import DEFAULT_LAYER_POLICY

        boundaries = [0.0, 10.0, 24.0]
        shifted = _protocol_layer_boundaries_with_vacuum(boundaries)

        z_vacuum = DEFAULT_LAYER_POLICY.z_vacuum_angstrom
        assert shifted == pytest.approx([z + z_vacuum for z in boundaries])

    def test_protocol_boundaries_respect_custom_vacuum(self) -> None:
        boundaries = [0.0, 10.0, 24.0]
        shifted = _protocol_layer_boundaries_with_vacuum(boundaries, z_vacuum=35.0)
        assert shifted == pytest.approx([35.0, 45.0, 59.0])

    def test_submit_data_file_has_z_vacuum(self, tmp_path: Path) -> None:
        """Combined data file zhi must include 2*z_vacuum beyond slab height."""
        from contracts.policies.layer import DEFAULT_LAYER_POLICY

        binder_path = tmp_path / "binder.data"
        crystal_path = tmp_path / "crystal.data"
        _write_binder_data_file(binder_path)
        _write_crystal_data_file(crystal_path)

        binder_src = _make_source(
            binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1"
        )
        crystal_src = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )

        sources = [crystal_src, binder_src]
        geometry = _combine_sources_to_geometry(sources, inter_layer_gap=2.0)
        out_path = tmp_path / "combined.data"
        _write_combined_lammps_data(out_path, geometry, sources=sources)

        content = out_path.read_text()
        # Parse zhi from data file
        for line in content.split("\n"):
            if "zlo zhi" in line:
                parts = line.split()
                zhi = float(parts[1])
                break
        else:
            pytest.fail("zlo zhi line not found in data file")

        slab_height = geometry.box_size[2]
        z_vacuum = DEFAULT_LAYER_POLICY.z_vacuum_angstrom
        expected_zhi = slab_height + 2 * z_vacuum
        assert zhi == pytest.approx(expected_zhi, abs=0.01)

    def test_submit_data_atom_z_shifted_by_vacuum(self, tmp_path: Path) -> None:
        """Atom z-coordinates in data file must be offset by z_vacuum."""
        from contracts.policies.layer import DEFAULT_LAYER_POLICY

        binder_path = tmp_path / "binder.data"
        crystal_path = tmp_path / "crystal.data"
        _write_binder_data_file(binder_path)
        _write_crystal_data_file(crystal_path)

        binder_src = _make_source(
            binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1"
        )
        crystal_src = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )

        sources = [crystal_src, binder_src]
        geometry = _combine_sources_to_geometry(sources, inter_layer_gap=2.0)
        out_path = tmp_path / "combined.data"
        _write_combined_lammps_data(out_path, geometry, sources=sources)

        content = out_path.read_text()
        # Parse atom z-coordinates
        in_atoms = False
        atom_zs: list[float] = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("Atoms"):
                in_atoms = True
                continue
            if in_atoms and stripped == "":
                continue
            if in_atoms:
                if stripped and not stripped[0].isdigit():
                    break
                parts = stripped.split()
                if len(parts) >= 7:
                    atom_zs.append(float(parts[6]))

        z_vacuum = DEFAULT_LAYER_POLICY.z_vacuum_angstrom
        # All atom z must be >= z_vacuum (shifted from 0)
        assert all(z >= z_vacuum - 0.01 for z in atom_zs)

    def test_submit_data_respects_custom_vacuum(self, tmp_path: Path) -> None:
        binder_path = tmp_path / "binder.data"
        crystal_path = tmp_path / "crystal.data"
        _write_binder_data_file(binder_path)
        _write_crystal_data_file(crystal_path)

        binder_src = _make_source(
            binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1"
        )
        crystal_src = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )

        sources = [crystal_src, binder_src]
        geometry = _combine_sources_to_geometry(sources, inter_layer_gap=2.0)
        out_path = tmp_path / "combined.data"
        _write_combined_lammps_data(out_path, geometry, sources=sources, z_vacuum=35.0)

        content = out_path.read_text()
        for line in content.split("\n"):
            if "zlo zhi" in line:
                parts = line.split()
                zhi = float(parts[1])
                break
        else:
            pytest.fail("zlo zhi line not found in data file")

        expected_zhi = geometry.box_size[2] + 70.0
        assert zhi == pytest.approx(expected_zhi, abs=0.01)

    def test_preview_geometry_no_vacuum(self, tmp_path: Path) -> None:
        """Preview geometry box_size z must be slab height without vacuum."""
        binder_path = tmp_path / "binder.data"
        crystal_path = tmp_path / "crystal.data"
        _write_binder_data_file(binder_path)
        _write_crystal_data_file(crystal_path)

        binder_src = _make_source(
            binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1"
        )
        crystal_src = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )

        sources = [crystal_src, binder_src]
        geometry = _combine_sources_to_geometry(sources, inter_layer_gap=2.0)

        # Crystal lz=10, binder lz=12, gap=2 → slab=24
        expected_slab = 10.0 + 12.0 + 2.0
        assert geometry.box_size[2] == pytest.approx(expected_slab, abs=0.01)


class TestAffineRescaleValidation:
    """_validate_checks must report rescale factor safety."""

    def test_rescale_check_pass_for_matching_xy(self, tmp_path: Path) -> None:
        b1 = tmp_path / "b1.data"
        b2 = tmp_path / "b2.data"
        _write_binder_data_file(b1, lx=50.0, ly=50.0, lz=10.0)
        _write_binder_data_file(b2, lx=50.0, ly=50.0, lz=10.0)
        s1 = _make_source(b1, source_type=LayerSourceType.BINDER_CELL, source_id="b1")
        s2 = _make_source(b2, source_type=LayerSourceType.BINDER_CELL, source_id="b2")

        checks = _validate_checks([s1, s2], xy_tolerance_pct=10.0, min_xy_to_z_ratio=0.5)
        rescale_check = next(c for c in checks if c.code == "affine_rescale")
        assert rescale_check.status == "pass"
        assert "No affine rescaling needed" in rescale_check.message

    def test_rescale_check_pass_for_small_mismatch(self, tmp_path: Path) -> None:
        crystal_path = tmp_path / "crystal.data"
        binder_path = tmp_path / "binder.data"
        _write_crystal_data_file(crystal_path, lx=49.0, ly=49.0, lz=10.0)
        _write_binder_data_file(binder_path, lx=50.0, ly=50.0, lz=12.0)
        c = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )
        b = _make_source(binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1")

        checks = _validate_checks([c, b], xy_tolerance_pct=10.0, min_xy_to_z_ratio=0.5)
        rescale_check = next(ch for ch in checks if ch.code == "affine_rescale")
        assert rescale_check.status == "pass"
        assert rescale_check.details["max_rescale_pct"] == pytest.approx(2.0, abs=0.1)

    def test_rescale_check_warn_for_large_mismatch(self, tmp_path: Path) -> None:
        crystal_path = tmp_path / "crystal.data"
        binder_path = tmp_path / "binder.data"
        # 8% mismatch: exceeds warn (5%) but under hard limit (10%)
        _write_crystal_data_file(crystal_path, lx=46.0, ly=46.0, lz=10.0)
        _write_binder_data_file(binder_path, lx=50.0, ly=50.0, lz=12.0)
        c = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )
        b = _make_source(binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1")

        checks = _validate_checks([c, b], xy_tolerance_pct=20.0, min_xy_to_z_ratio=0.5)
        rescale_check = next(ch for ch in checks if ch.code == "affine_rescale")
        assert rescale_check.status == "warn"

    def test_rescale_check_fail_for_excessive_mismatch(self, tmp_path: Path) -> None:
        crystal_path = tmp_path / "crystal.data"
        binder_path = tmp_path / "binder.data"
        # 20% mismatch: exceeds hard limit (10%)
        _write_crystal_data_file(crystal_path, lx=40.0, ly=40.0, lz=10.0)
        _write_binder_data_file(binder_path, lx=50.0, ly=50.0, lz=12.0)
        c = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )
        b = _make_source(binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1")

        checks = _validate_checks([c, b], xy_tolerance_pct=50.0, min_xy_to_z_ratio=0.5)
        rescale_check = next(ch for ch in checks if ch.code == "affine_rescale")
        assert rescale_check.status == "fail"

    def test_rescale_check_multilayer_uses_bottom_crystal(self, tmp_path: Path) -> None:
        """Validation must use bottom crystal as reference, not max of all crystals."""
        c1_path = tmp_path / "c1.data"
        b1_path = tmp_path / "b1.data"
        b2_path = tmp_path / "b2.data"
        c2_path = tmp_path / "c2.data"
        # Bottom crystal 48, binders 50 and 51, top crystal 55
        _write_crystal_data_file(c1_path, lx=48.0, ly=48.0, lz=10.0)
        _write_binder_data_file(b1_path, lx=50.0, ly=50.0, lz=12.0)
        _write_binder_data_file(b2_path, lx=51.0, ly=51.0, lz=12.0)
        _write_crystal_data_file(c2_path, lx=55.0, ly=55.0, lz=10.0)

        c1 = _make_source(c1_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1")
        b1 = _make_source(b1_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1")
        b2 = _make_source(b2_path, source_type=LayerSourceType.BINDER_CELL, source_id="b2")
        c2 = _make_source(c2_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c2")

        checks = _validate_checks([c1, b1, b2, c2], xy_tolerance_pct=50.0, min_xy_to_z_ratio=0.1)
        rescale_check = next(ch for ch in checks if ch.code == "affine_rescale")

        # b1: |1 - 48/50| = 4%, b2: |1 - 48/51| = 5.88%
        # Reference is bottom crystal (48), so max_rescale ≈ 5.88%
        # If max(48,55)=55 were used, b1 would be 10% and b2 would be 7.8%
        assert rescale_check.details["max_rescale_pct"] == pytest.approx(5.88, abs=0.2)
        # Both non-crystal layers reported
        per_layer = rescale_check.details["per_layer"]
        assert len(per_layer) == 2
        # Check scale factors are relative to 48, not 55
        for detail in per_layer:
            assert detail["scale_x"] < 1.0  # 48/50 and 48/51 are both < 1


# ---------------------------------------------------------------------------
# Crystal grip z-range computation
# ---------------------------------------------------------------------------


class TestComputeCrystalGripRanges:
    """Test _compute_crystal_grip_ranges helper."""

    def test_compute_crystal_grip_for_sandwich(self, tmp_path: Path) -> None:
        """Crystal-binder-crystal → both grip ranges returned."""
        crystal_path = tmp_path / "crystal.data"
        binder_path = tmp_path / "binder.data"
        _write_crystal_data_file(crystal_path)
        _write_binder_data_file(binder_path)

        c1 = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )
        b1 = _make_source(binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1")
        c2 = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c2"
        )

        # 3 layers: boundaries = [z0, z1, z2, z3, z4, z5]
        shifted = [25.0, 35.0, 37.0, 49.0, 51.0, 61.0]
        bottom, top = _compute_crystal_grip_ranges([c1, b1, c2], shifted)

        assert bottom == (25.0, 35.0)
        assert top == (51.0, 61.0)

    def test_compute_crystal_grip_single_crystal(self, tmp_path: Path) -> None:
        """Crystal-binder (one-sided) → only bottom returned."""
        crystal_path = tmp_path / "crystal.data"
        binder_path = tmp_path / "binder.data"
        _write_crystal_data_file(crystal_path)
        _write_binder_data_file(binder_path)

        c1 = _make_source(
            crystal_path, source_type=LayerSourceType.CRYSTAL_STRUCTURE, source_id="c1"
        )
        b1 = _make_source(binder_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1")

        shifted = [25.0, 35.0, 37.0, 49.0]
        bottom, top = _compute_crystal_grip_ranges([c1, b1], shifted)

        assert bottom == (25.0, 35.0)
        assert top is None

    def test_compute_crystal_grip_no_crystal(self, tmp_path: Path) -> None:
        """Binder-binder → (None, None)."""
        b1_path = tmp_path / "b1.data"
        b2_path = tmp_path / "b2.data"
        _write_binder_data_file(b1_path)
        _write_binder_data_file(b2_path)

        b1 = _make_source(b1_path, source_type=LayerSourceType.BINDER_CELL, source_id="b1")
        b2 = _make_source(b2_path, source_type=LayerSourceType.BINDER_CELL, source_id="b2")

        shifted = [25.0, 37.0, 39.0, 51.0]
        bottom, top = _compute_crystal_grip_ranges([b1, b2], shifted)

        assert bottom is None
        assert top is None


# ---------------------------------------------------------------------------
# Crystal additive label encoding
# ---------------------------------------------------------------------------


class TestCrystalAdditiveLabel:
    """Test _crystal_additive_label helper for exp_id additive slot."""

    def test_full_label(self):
        from features.layered_structures.service import _crystal_additive_label

        assert _crystal_additive_label("SiO2", "001", True) == "SiO2-001-OH"

    def test_no_hydroxyl(self):
        from features.layered_structures.service import _crystal_additive_label

        assert _crystal_additive_label("SiO2", "110", False) == "SiO2-110"

    def test_surface_only(self):
        from features.layered_structures.service import _crystal_additive_label

        assert _crystal_additive_label("CaCO3", "001", None) == "CaCO3-001"

    def test_material_only(self):
        from features.layered_structures.service import _crystal_additive_label

        assert _crystal_additive_label("SiO2", None, None) == "SiO2"

    def test_no_underscore_in_label(self):
        """Label must not contain '_' to stay compatible with parse_exp_id."""
        from features.layered_structures.service import _crystal_additive_label

        label = _crystal_additive_label("Al2O3", "111", True)
        assert "_" not in label
        assert label == "Al2O3-111-OH"
