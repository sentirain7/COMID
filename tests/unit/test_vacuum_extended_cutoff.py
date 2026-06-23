"""Unit tests for Method 1a — vacuum_intra_subtraction_extended_cutoff.

Validates:
- ``compute_max_pairwise_distance_from_data_file`` parses LAMMPS data files.
- ``resolve_vacuum_cutoff`` returns legacy 12 Å when extended=False, and
  max(50, 2×extent) when extended=True with a valid data file.
- ``generate_organic_ff`` emits the extended cutoff in the pair_style line
  for SINGLE_MOLECULE_VACUUM with an explicit ``vacuum_cutoff`` override.
- The cutoff > molecular_extent invariant holds (Method 1a guarantee).
- Env-var opt-in (`ASPHALT_VACUUM_EXTENDED_CUTOFF=1`) routes through
  ``vacuum_extended_cutoff_enabled``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.schemas import StudyType
from protocols.lammps_force_field import (
    VACUUM_DEFAULT_CUTOFF_A,
    VACUUM_EXTENDED_EXTENT_MULTIPLIER,
    VACUUM_EXTENDED_MIN_CUTOFF_A,
    compute_max_pairwise_distance_from_data_file,
    generate_organic_ff,
    resolve_vacuum_cutoff,
    vacuum_extended_cutoff_enabled,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_data_file(tmp_path: Path, coords: list[tuple[float, float, float]]) -> Path:
    """Write a minimal LAMMPS 'full' style data file with given atom coords."""
    n = len(coords)
    lines = [
        "LAMMPS data file (test fixture)",
        "",
        f"{n} atoms",
        "1 atom types",
        "",
        "-100.0 100.0 xlo xhi",
        "-100.0 100.0 ylo yhi",
        "-100.0 100.0 zlo zhi",
        "",
        "Masses",
        "",
        "1 12.011",
        "",
        "Atoms",
        "",
    ]
    for idx, (x, y, z) in enumerate(coords, start=1):
        # full style: atom_id mol_id atom_type charge x y z
        lines.append(f"{idx} 1 1 0.0 {x:.6f} {y:.6f} {z:.6f}")
    path = tmp_path / "test_mol.data"
    path.write_text("\n".join(lines) + "\n")
    return path


# ---------------------------------------------------------------------------
# compute_max_pairwise_distance_from_data_file
# ---------------------------------------------------------------------------


class TestExtentParser:
    def test_two_atoms_along_x(self, tmp_path: Path):
        f = _write_data_file(tmp_path, [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)])
        assert compute_max_pairwise_distance_from_data_file(str(f)) == pytest.approx(10.0)

    def test_diagonal_distance(self, tmp_path: Path):
        f = _write_data_file(tmp_path, [(0.0, 0.0, 0.0), (3.0, 4.0, 0.0)])
        assert compute_max_pairwise_distance_from_data_file(str(f)) == pytest.approx(5.0)

    def test_picks_max_among_many(self, tmp_path: Path):
        coords = [
            (0.0, 0.0, 0.0),
            (5.0, 0.0, 0.0),
            (5.0, 5.0, 0.0),
            (-10.0, 0.0, 0.0),  # farthest from (5,5,0) — distance sqrt(225+25)=15.81
        ]
        f = _write_data_file(tmp_path, coords)
        d = compute_max_pairwise_distance_from_data_file(str(f))
        assert d == pytest.approx((225 + 25) ** 0.5, rel=1e-6)

    def test_missing_file_returns_zero(self):
        assert compute_max_pairwise_distance_from_data_file("/nonexistent/path.data") == 0.0

    def test_empty_string_returns_zero(self):
        assert compute_max_pairwise_distance_from_data_file("") == 0.0

    def test_single_atom_returns_zero(self, tmp_path: Path):
        f = _write_data_file(tmp_path, [(0.0, 0.0, 0.0)])
        assert compute_max_pairwise_distance_from_data_file(str(f)) == 0.0


# ---------------------------------------------------------------------------
# resolve_vacuum_cutoff
# ---------------------------------------------------------------------------


class TestResolveVacuumCutoff:
    def test_baseline_when_extended_false(self):
        cutoff, tag = resolve_vacuum_cutoff("/anything", extended=False)
        assert cutoff == VACUUM_DEFAULT_CUTOFF_A
        assert tag == "single_molecule_vacuum"

    def test_extended_uses_min_when_extent_small(self, tmp_path: Path):
        # extent = 5 Å → 2×5 = 10 Å < 50 Å → cutoff clamps to 50
        f = _write_data_file(tmp_path, [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0)])
        cutoff, tag = resolve_vacuum_cutoff(str(f), extended=True)
        assert cutoff == VACUUM_EXTENDED_MIN_CUTOFF_A
        assert tag == "single_molecule_vacuum_adaptive_cutoff"

    def test_extended_scales_with_extent(self, tmp_path: Path):
        # extent = 40 Å → 2×40 = 80 Å > 50 Å
        f = _write_data_file(tmp_path, [(0.0, 0.0, 0.0), (40.0, 0.0, 0.0)])
        cutoff, tag = resolve_vacuum_cutoff(str(f), extended=True)
        assert cutoff == pytest.approx(80.0)
        assert tag == "single_molecule_vacuum_adaptive_cutoff"

    def test_cutoff_strictly_greater_than_extent(self, tmp_path: Path):
        """Method 1a invariant: cutoff > molecular_extent (so direct sum captures all pairs)."""
        for extent in [3.0, 12.0, 25.0, 40.0, 60.0]:
            f = _write_data_file(tmp_path, [(0.0, 0.0, 0.0), (extent, 0.0, 0.0)])
            cutoff, _ = resolve_vacuum_cutoff(str(f), extended=True)
            assert cutoff > extent, (
                f"Method 1a invariant violated: cutoff={cutoff} not > extent={extent}"
            )

    def test_invalid_path_falls_back_to_default(self):
        cutoff, tag = resolve_vacuum_cutoff("/nope.data", extended=True)
        assert cutoff == VACUUM_DEFAULT_CUTOFF_A
        assert tag == "single_molecule_vacuum"

    def test_extent_multiplier_constant(self):
        assert VACUUM_EXTENDED_EXTENT_MULTIPLIER == 2.0


# ---------------------------------------------------------------------------
# vacuum_extended_cutoff_enabled (env var opt-in)
# ---------------------------------------------------------------------------


class TestEnvVarOptIn:
    def test_default_off(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ASPHALT_VACUUM_EXTENDED_CUTOFF", raising=False)
        assert vacuum_extended_cutoff_enabled() is False

    def test_enabled_with_one(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ASPHALT_VACUUM_EXTENDED_CUTOFF", "1")
        assert vacuum_extended_cutoff_enabled() is True

    def test_enabled_with_true(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ASPHALT_VACUUM_EXTENDED_CUTOFF", "true")
        assert vacuum_extended_cutoff_enabled() is True

    def test_disabled_with_zero(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ASPHALT_VACUUM_EXTENDED_CUTOFF", "0")
        assert vacuum_extended_cutoff_enabled() is False


# ---------------------------------------------------------------------------
# generate_organic_ff with vacuum_cutoff override
# ---------------------------------------------------------------------------


class TestGenerateOrganicFFExtendedCutoff:
    def test_baseline_vacuum_uses_12A(self):
        text = generate_organic_ff(
            "bulk_ff_gaff2",
            has_charges=True,
            has_bonds=True,
            study_type=StudyType.SINGLE_MOLECULE_VACUUM,
            vacuum_cutoff=None,
        )
        assert "lj/cut/coul/cut 12.0" in text
        assert "kspace_style" not in text  # vacuum: no kspace

    def test_extended_vacuum_uses_override(self):
        text = generate_organic_ff(
            "bulk_ff_gaff2",
            has_charges=True,
            has_bonds=True,
            study_type=StudyType.SINGLE_MOLECULE_VACUUM,
            vacuum_cutoff=80.0,
        )
        assert "lj/cut/coul/cut 80" in text
        assert "Method 1a" in text  # ff_label annotated
        assert "kspace_style" not in text

    def test_bulk_ignores_vacuum_cutoff(self):
        text = generate_organic_ff(
            "bulk_ff_gaff2",
            has_charges=True,
            has_bonds=True,
            study_type=StudyType.BULK,
            vacuum_cutoff=80.0,  # ignored for bulk
        )
        assert "lj/cut/coul/long 12.0" in text
        assert "kspace_style" in text

    def test_no_charges_vacuum_uses_extended(self):
        text = generate_organic_ff(
            "bulk_ff_gaff2",
            has_charges=False,
            has_bonds=True,
            study_type=StudyType.SINGLE_MOLECULE_VACUUM,
            vacuum_cutoff=80.0,
        )
        assert "lj/cut 80" in text


# ---------------------------------------------------------------------------
# end-to-end: generate_force_field with resolved method on ProtocolChain
# ---------------------------------------------------------------------------


class TestGenerateForceFieldEndToEnd:
    def test_missing_chain_method_defaults_to_legacy_cutoff_even_if_env_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from contracts.schemas import FFType, RunTier
        from protocols.lammps_force_field import generate_force_field
        from protocols.protocol_chain import ProtocolChain

        monkeypatch.setenv("ASPHALT_VACUUM_EXTENDED_CUTOFF", "1")
        f = _write_data_file(tmp_path, [(0.0, 0.0, 0.0), (40.0, 0.0, 0.0)])
        chain = ProtocolChain(
            tier=RunTier.SCREENING,
            steps=[],
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            study_type=StudyType.SINGLE_MOLECULE_VACUUM,
            data_file_path=str(f),
        )
        text = generate_force_field(chain, has_charges=True, has_bonds=True)
        assert "lj/cut/coul/cut 12.0" in text
        assert "lj/cut/coul/cut 80" not in text

    def test_explicit_method_1a_produces_extended_cutoff_independent_of_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from contracts.schemas import FFType, RunTier
        from protocols.lammps_force_field import generate_force_field
        from protocols.protocol_chain import ProtocolChain

        monkeypatch.delenv("ASPHALT_VACUUM_EXTENDED_CUTOFF", raising=False)
        # extent = 40 Å → cutoff = 80 Å
        f = _write_data_file(tmp_path, [(0.0, 0.0, 0.0), (40.0, 0.0, 0.0)])
        chain = ProtocolChain(
            tier=RunTier.SCREENING,
            steps=[],
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            study_type=StudyType.SINGLE_MOLECULE_VACUUM,
            data_file_path=str(f),
            e_intra_method="single_molecule_vacuum_adaptive_cutoff",
        )
        text = generate_force_field(chain, has_charges=True, has_bonds=True)
        assert "lj/cut/coul/cut 80" in text
        assert "Method 1a" in text

    def test_explicit_method_1_forces_legacy_cutoff_even_if_env_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from contracts.schemas import FFType, RunTier
        from protocols.lammps_force_field import generate_force_field
        from protocols.protocol_chain import ProtocolChain

        monkeypatch.setenv("ASPHALT_VACUUM_EXTENDED_CUTOFF", "1")
        f = _write_data_file(tmp_path, [(0.0, 0.0, 0.0), (40.0, 0.0, 0.0)])
        chain = ProtocolChain(
            tier=RunTier.SCREENING,
            steps=[],
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            study_type=StudyType.SINGLE_MOLECULE_VACUUM,
            data_file_path=str(f),
            e_intra_method="single_molecule_vacuum",
        )
        text = generate_force_field(chain, has_charges=True, has_bonds=True)
        assert "lj/cut/coul/cut 12.0" in text
        assert "lj/cut/coul/cut 80" not in text
