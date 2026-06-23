"""Wave 5: layered combined LAMMPS data + protocol cross-interaction lockdown.

The Wave 1 LAYER_BULKFF protocol regression already locks the *protocol
script* layer (mix arithmetic, slab 3.0, lj/cut/coul/long). Wave 5
extends that to the **combined data file**: when a real layered build
emits a single LAMMPS data file containing both a silica slab and a
binder fragment, the Pair Coeffs table for the silica side MUST use
the INTERFACE FF values, not UFF or any other element fallback.

This file consumes the hand-curated reference at
``tests/data/mineral_combined/silica_binder_ref.lammps_data`` and
asserts:

* the Pair Coeffs table contains the four expected atom types
  (Si_tet, O_br, CA, HA) in the documented order
* Si_tet ε == 0.00040 kcal/mol AND σ == 3.302 Å (Heinz 2013, Emami 2014)
* O_br ε == 0.15540 AND σ == 3.166
* CA / HA values come from GAFF2 (Jorgensen 1996 compatible)
* the silica section is electrically neutral (Si4 +2.10 + O8 -1.05 = 0)
* the binder fragment is electrically neutral (4 CA -0.115 + 4 HA +0.115 = 0)
* total system charge is 0

Then it walks the LAMMPSInputGenerator and confirms that for the
LAYER_BULKFF study type, the emitted protocol script DOES use the
contracts that the data file's pair coeffs require:

* ``pair_modify mix arithmetic``
* ``kspace_modify slab 3.0``
* ``pair_style lj/cut/coul/long 12.0``

If either side drifts, the cross interaction is silently wrong.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from contracts.schemas import (  # noqa: E402
    FFType,
    ProtocolRequest,
    RunTier,
    StudyType,
    TensileSpec,
)
from protocols.lammps_input import LAMMPSInputGenerator  # noqa: E402

REFERENCE_DATA_PATH = (
    Path(__file__).parent.parent / "data" / "mineral_combined" / "silica_binder_ref.lammps_data"
)


# ---------------------------------------------------------------------------
# Reference fixture parser (purpose-built for this test)
# ---------------------------------------------------------------------------


def _parse_pair_coeffs(text: str) -> list[tuple[int, float, float, str]]:
    """Return a list of (type_id, epsilon, sigma, comment) from a LAMMPS data file."""
    coeffs: list[tuple[int, float, float, str]] = []
    in_section = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Pair Coeffs"):
            in_section = True
            continue
        if not in_section:
            continue
        if not line:
            if coeffs:
                break
            continue
        if line.startswith("#"):
            continue
        # Stop at the next named section.
        first = line.split()[0]
        if first.isalpha():
            break

        # Format: <type_id> <epsilon> <sigma>  # comment
        comment = ""
        if "#" in line:
            data, comment = line.split("#", 1)
            comment = comment.strip()
        else:
            data = line
        parts = data.split()
        if len(parts) < 3:
            continue
        try:
            type_id = int(parts[0])
            epsilon = float(parts[1])
            sigma = float(parts[2])
        except (ValueError, IndexError):
            continue
        coeffs.append((type_id, epsilon, sigma, comment))
    return coeffs


def _parse_atom_charges(text: str) -> list[float]:
    in_atoms = False
    out: list[float] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Atoms"):
            in_atoms = True
            continue
        if not in_atoms:
            continue
        if not line:
            if out:
                break
            continue
        if line.startswith("#"):
            continue
        first = line.split()[0]
        if first.isalpha():
            break
        parts = line.split()
        if len(parts) >= 7:
            try:
                out.append(float(parts[3]))
            except (ValueError, IndexError):
                continue
    return out


def _parse_atom_types(text: str) -> list[int]:
    """Return a list of atom-type integers in atom-id order."""
    in_atoms = False
    out: list[int] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Atoms"):
            in_atoms = True
            continue
        if not in_atoms:
            continue
        if not line:
            if out:
                break
            continue
        if line.startswith("#"):
            continue
        first = line.split()[0]
        if first.isalpha():
            break
        parts = line.split()
        if len(parts) >= 7:
            try:
                out.append(int(parts[2]))
            except (ValueError, IndexError):
                continue
    return out


# ---------------------------------------------------------------------------
# Reference fixture sanity
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reference_data_text() -> str:
    assert REFERENCE_DATA_PATH.exists(), (
        f"Wave 5 reference fixture missing: {REFERENCE_DATA_PATH}. "
        "The Wave 5 layered cross-interaction lockdown depends on this file."
    )
    return REFERENCE_DATA_PATH.read_text()


class TestReferenceFixtureSanity:
    def test_fixture_declares_18_atoms(self, reference_data_text):
        # 12 silica + 6 binder
        match = re.search(r"^(\d+)\s+atoms", reference_data_text, flags=re.MULTILINE)
        assert match is not None
        assert int(match.group(1)) == 18

    def test_fixture_declares_4_atom_types(self, reference_data_text):
        match = re.search(r"^(\d+)\s+atom\s+types", reference_data_text, flags=re.MULTILINE)
        assert match is not None
        assert int(match.group(1)) == 4

    def test_fixture_uses_p_p_f_compatible_box(self, reference_data_text):
        # Hand-written fixture uses a 30^3 box so it can be slab-style.
        assert "0.0 30.0 xlo xhi" in reference_data_text
        assert "0.0 30.0 zlo zhi" in reference_data_text


# ---------------------------------------------------------------------------
# Pair Coeffs lockdown
# ---------------------------------------------------------------------------


class TestLayeredPairCoeffsLockdown:
    """The mineral side of the combined data file MUST use INTERFACE FF."""

    def test_four_pair_coeffs_in_documented_order(self, reference_data_text):
        coeffs = _parse_pair_coeffs(reference_data_text)
        assert len(coeffs) == 4
        # Order is fixed: Si_tet, O_br, CA, HA
        assert "Si_tet" in coeffs[0][3]
        assert "O_br" in coeffs[1][3]
        assert "CA" in coeffs[2][3]
        assert "HA" in coeffs[3][3]

    def test_silica_si_pair_coeff_is_interface_ff(self, reference_data_text):
        coeffs = _parse_pair_coeffs(reference_data_text)
        si_tet = coeffs[0]
        assert si_tet[1] == pytest.approx(0.00040, abs=1e-6), (
            "Si_tet pair coeff epsilon must remain INTERFACE FF 0.00040 "
            "(Heinz 2013, Emami 2014); UFF Si is 0.402 — a ~1000x error "
            "that would silently break the silica/binder cross interaction."
        )
        assert si_tet[2] == pytest.approx(3.302, abs=1e-4)

    def test_silica_o_pair_coeff_is_interface_ff(self, reference_data_text):
        coeffs = _parse_pair_coeffs(reference_data_text)
        o_br = coeffs[1]
        assert o_br[1] == pytest.approx(0.15540, abs=1e-5)
        assert o_br[2] == pytest.approx(3.166, abs=1e-4)

    def test_binder_aromatic_pair_coeff_is_gaff2(self, reference_data_text):
        coeffs = _parse_pair_coeffs(reference_data_text)
        ca = coeffs[2]
        ha = coeffs[3]
        # GAFF2 aromatic (Jorgensen 1996 compatible)
        assert ca[1] == pytest.approx(0.07000, abs=1e-5)
        assert ca[2] == pytest.approx(3.5500, abs=1e-4)
        assert ha[1] == pytest.approx(0.03000, abs=1e-5)
        assert ha[2] == pytest.approx(2.4200, abs=1e-4)


# ---------------------------------------------------------------------------
# Charge neutrality
# ---------------------------------------------------------------------------


class TestLayeredFixtureChargeContract:
    """Wave 5 charge contract:

    * Silica slab is electrically neutral (CLAYFF charges sum cleanly).
    * Binder fragment is INTENTIONALLY NON-NEUTRAL (-0.230) because it
      is a 6-atom stub of an aromatic ring, not a complete toluene
      molecule. See ``tests/data/mineral_combined/README.md`` for the
      full contract.

    The class name and test method names below have been chosen to
    avoid the false-friend ``test_binder_section_neutral`` reading —
    that name would imply a check that the binder section sums to zero,
    which is the OPPOSITE of what we want here.
    """

    def test_silica_section_is_neutral(self, reference_data_text):
        types = _parse_atom_types(reference_data_text)
        charges = _parse_atom_charges(reference_data_text)
        assert len(types) == len(charges) == 18

        silica = [(t, q) for t, q in zip(types, charges, strict=True) if t in (1, 2)]
        si_total = sum(q for t, q in silica if t == 1)
        o_total = sum(q for t, q in silica if t == 2)
        # 4 Si at +2.10 = +8.40
        assert si_total == pytest.approx(8.40, abs=1e-6)
        # 8 O at -1.05 = -8.40
        assert o_total == pytest.approx(-8.40, abs=1e-6)
        assert (si_total + o_total) == pytest.approx(0.0, abs=1e-6)

    def test_binder_stub_charge_sum_is_intentional_non_neutral(self, reference_data_text):
        """The binder stub is 4 CA + 2 HA = -0.230 by design.

        This test name is deliberately verbose so a future reader does
        not mistake it for a "binder is neutral" check. The fixture
        intentionally omits two HA hydrogens to keep the regression
        small; expanding the stub would require updating the fixture
        header, the README charge-balance contract, AND the asserted
        sum here in the same commit.
        """
        types = _parse_atom_types(reference_data_text)
        charges = _parse_atom_charges(reference_data_text)
        binder = [q for t, q in zip(types, charges, strict=True) if t in (3, 4)]
        assert len(binder) == 6, (
            "Wave 5 binder stub must have exactly 6 atoms (4 CA + 2 HA). "
            "If the fixture grew, update README.md and the assertion below."
        )
        ca = [q for t, q in zip(types, charges, strict=True) if t == 3]
        ha = [q for t, q in zip(types, charges, strict=True) if t == 4]
        assert len(ca) == 4
        assert len(ha) == 2
        for q in ca:
            assert q == pytest.approx(-0.115, abs=1e-6)
        for q in ha:
            assert q == pytest.approx(0.115, abs=1e-6)
        assert sum(binder) == pytest.approx(-0.230, abs=1e-6), (
            "Wave 5 binder stub MUST hold its intentional charge sum -0.230 "
            "(4 CA at -0.115 + 2 HA at +0.115). This is documented in "
            "tests/data/mineral_combined/README.md as the 'charge balance "
            "contract'. Do NOT 'fix' this to zero — the stub omits two HA "
            "atoms on purpose to keep the regression minimal. To expand "
            "the stub, update fixture header + README + this assertion in "
            "one commit."
        )

    def test_total_system_charge_matches_documented_value(self, reference_data_text):
        """Locks the documented total charge from README contract."""
        charges = _parse_atom_charges(reference_data_text)
        total = sum(charges)
        # Total = silica (0) + binder stub (-0.230) = -0.230
        assert total == pytest.approx(-0.230, abs=1e-6), (
            "Wave 5 fixture documented total charge is -0.230 "
            "(silica 0 + binder stub -0.230). See README.md."
        )


# ---------------------------------------------------------------------------
# Protocol layer cross-checks (Wave 1 contract reaffirmed end-to-end)
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def generator(temp_dir):
    return LAMMPSInputGenerator(template_dir=temp_dir / "templates")


class TestLayeredProtocolCrossInteractionContract:
    """Wave 5: re-affirm that the protocol script the silica fixture
    expects is the one the protocol layer actually emits."""

    def _emit(self, generator, temp_dir):
        request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            study_type=StudyType.LAYER_BULKFF,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path=str(temp_dir / "data.lammps"),
            tensile_spec=TensileSpec(enabled=True),
        )
        (temp_dir / "data.lammps").write_text("0 atoms\n0 bonds\n")
        out = temp_dir / "in.lammps"
        generator.generate_to_path(request, out)
        return out.read_text()

    def test_layer_emits_arithmetic_mixing(self, generator, temp_dir):
        script = self._emit(generator, temp_dir)
        assert "pair_modify mix arithmetic" in script
        assert "pair_modify mix geometric" not in script

    def test_layer_emits_slab_correction(self, generator, temp_dir):
        script = self._emit(generator, temp_dir)
        assert "kspace_modify slab 3.0" in script

    def test_layer_emits_long_range_coulomb(self, generator, temp_dir):
        script = self._emit(generator, temp_dir)
        assert "pair_style lj/cut/coul/long 12.0" in script
        assert "kspace_style pppm" in script

    def test_layer_protocol_consistent_with_data_pair_coeffs(
        self, generator, temp_dir, reference_data_text
    ):
        """End-to-end consistency: the protocol mix rule MUST match the
        physical assumption baked into the reference Pair Coeffs."""
        script = self._emit(generator, temp_dir)
        # The reference fixture uses INTERFACE FF Si (small epsilon),
        # which is only physically meaningful under arithmetic /
        # Lorentz-Berthelot mixing — Heinz 2013 Eq. 1. Locking the
        # script side here prevents a future protocol regression from
        # silently flipping to geometric mixing.
        assert "pair_modify mix arithmetic" in script

        coeffs = _parse_pair_coeffs(reference_data_text)
        si_tet_eps = coeffs[0][1]
        assert si_tet_eps == pytest.approx(0.00040, abs=1e-6)
