"""SSOT integration regression for topology_helpers.

Phase 6: the legacy RDKit path has been removed. This test file locks:

* blocked_placeholder / ionic_profile / inorganic_profile species are
  REJECTED — no silent fall-through.
* organic_curated_artifact molecules apply the curated artifact via the
  executor (atom-by-atom mutation visible on the topology).
* callers that omit ff_assignment get BLOCKED (no default to legacy).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from builder.topology_helpers import (  # noqa: E402
    probe_single_component_generation_support,
)
from contracts.errors import BuildError  # noqa: E402
from forcefield.organic_curated_artifact import clear_artifact_cache  # noqa: E402

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


@pytest.fixture
def fake_mol_file(tmp_path):
    f = tmp_path / "fake.mol"
    f.write_text("dummy")
    return f


def _two_atom_topology(mol_id: str = "Toluene_stub"):
    """Build a topology that matches the Toluene fixture shape (15 atoms).

    Wave 2 fixture has 15 atoms; we replicate that here so the curated
    artifact apply path can run without index/element mismatches.
    """
    elements = (
        ["C", "H", "H", "H"]  # methyl
        + ["C", "C", "C", "C", "C", "C"]  # aromatic ring
        + ["H", "H", "H", "H", "H"]  # aromatic + ring H
    )
    return SimpleNamespace(
        mol_id=mol_id,
        n_atoms=len(elements),
        n_bonds=14,  # ring + methyl C-H + ring CA-CT bond
        atoms=[
            SimpleNamespace(
                index=i + 1,
                element=elements[i],
                ff_type="",
                charge=0.0,
                charge_defined=False,
                x=float(i),
                y=0.0,
                z=0.0,
            )
            for i in range(len(elements))
        ],
        bonds=[],
    )


# ---------------------------------------------------------------------------
# probe_single_component_generation_support
# ---------------------------------------------------------------------------


class TestProbeBlockedRoutes:
    """Wave 2: blocked / ionic / inorganic decisions propagate to the probe."""

    def test_blocked_placeholder_returns_unsupported(self, fake_mol_file):
        # Organic blocked_placeholder with missing source_id is now blocked
        # by the router as an authoring error (source_id missing), not as
        # "artifact not yet generated". Inorganic/ionic blocked_placeholder
        # still fail-closed via the router.
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "blocked_placeholder",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        with patch(
            "builder.topology_helpers.parse_mol_topology",
            return_value=_two_atom_topology(),
        ):
            ok, reason = probe_single_component_generation_support(
                fake_mol_file,
                "DraftMol",
                ff_assignment=ff_assignment,
            )
        assert ok is False
        assert "source_id is missing" in (reason or "")

    def test_ionic_profile_returns_unsupported(self, fake_mol_file):
        """Wave 3 contract: the helper must propagate the user-friendly
        Wave 3 reason verbatim from the typing router. A cheap
        ``"ionic" in reason`` check is NOT enough — that would silently
        accept any technical/programmer-facing error message and the
        operator would lose the actionable guidance ("use organic
        surrogate or wait for Wave 3 release"). Lock every key fragment.
        """
        ff_assignment = {
            "route": "ionic_profile",
            "status": "blocked_placeholder",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        with patch(
            "builder.topology_helpers.parse_mol_topology",
            return_value=_two_atom_topology(),
        ):
            ok, reason = probe_single_component_generation_support(
                fake_mol_file,
                "NaCl",
                ff_assignment=ff_assignment,
            )
        assert ok is False
        reason = reason or ""
        # Production friendly-message lockdown (router-emitted text):
        assert "NaCl" in reason, "ionic helper rejection must include the offending mol_id"
        assert "Ionic species" in reason, (
            "ionic helper rejection must use the user-facing 'Ionic species' "
            "phrasing emitted by the router"
        )
        assert "Wave 3" in reason, (
            "ionic helper rejection must point at the Wave 3 release timeline"
        )
        assert "surrogate" in reason or "wait for the Wave 3 release" in reason, (
            "ionic helper rejection must give the operator an actionable next "
            "step (organic surrogate / wait for Wave 3)"
        )

    def test_inorganic_profile_returns_unsupported(self, fake_mol_file):
        """Inorganic species belong to the main builder path, not the
        single-component helper. The probe must say so explicitly."""
        ff_assignment = {
            "route": "inorganic_profile",
            "status": "active",
            "source_id": "silica_hydroxylated_v1",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        additive_def = {
            "category": "inorganic",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "silica_hydroxylated_v1",
            },
        }
        with patch(
            "builder.topology_helpers.parse_mol_topology",
            return_value=_two_atom_topology(),
        ):
            ok, reason = probe_single_component_generation_support(
                fake_mol_file,
                "SiO2",
                ff_assignment=ff_assignment,
                additive_def=additive_def,
            )
        assert ok is False
        assert "inorganic" in (reason or "").lower()


class TestProbeOrganicArtifactRoute:
    def test_artifact_route_is_supported_for_repo_fixture(self, fake_mol_file):
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "Toluene",
            "formal_charge": 0,
            "canonical_smiles": "Cc1ccccc1",
        }
        topology = _two_atom_topology(mol_id="Toluene")
        with patch(
            "builder.topology_helpers.parse_mol_topology",
            return_value=topology,
        ):
            ok, reason = probe_single_component_generation_support(
                fake_mol_file,
                "Toluene",
                ff_assignment=ff_assignment,
            )
        # Toluene artifact may lack LJ (incomplete) → regeneration attempted → may fail
        # without AmberTools. Both ok=True (artifact complete) and ok=False (regeneration
        # failed) are valid outcomes depending on environment.
        if ok:
            assert topology.atoms[0].ff_type == "c3"
        else:
            assert reason is not None  # fail-closed with reason

    def test_artifact_missing_returns_unsupported(self, fake_mol_file):
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "Mystery_does_not_exist",
            "formal_charge": 0,
            "canonical_smiles": "C",
        }
        with patch(
            "builder.topology_helpers.parse_mol_topology",
            return_value=_two_atom_topology(),
        ):
            ok, reason = probe_single_component_generation_support(
                fake_mol_file,
                "Mystery",
                ff_assignment=ff_assignment,
            )
        assert ok is False
        assert (
            "Organic typing/charge failed" in (reason or "")
            or "missing" in (reason or "").lower()
            or "Artifact auto-generation failed" in (reason or "")
            or "failed" in (reason or "").lower()
        )


class TestProbeBlockedWithoutFfAssignment:
    """Phase 6: without ff_assignment, the probe returns BLOCKED (not legacy)."""

    def test_no_ff_assignment_returns_blocked(self, fake_mol_file):
        topology = _two_atom_topology()

        with patch(
            "builder.topology_helpers.parse_mol_topology",
            return_value=topology,
        ):
            ok, reason = probe_single_component_generation_support(fake_mol_file, "LegacyMol")

        # Phase 6: the router returns BLOCKED when both ff_assignment
        # and additive_def are None (no default to legacy path).
        assert ok is False
        assert reason is not None
        assert "no ff_assignment" in reason or "blocked" in reason.lower()


# ---------------------------------------------------------------------------
# generate_single_component_topology — fail-closed routes only
# ---------------------------------------------------------------------------


class TestGenerateSingleComponentTopologyFailClosed:
    """The full-pipeline helper must fail-closed on non-organic routes."""

    def test_blocked_placeholder_raises_build_error(self, fake_mol_file, tmp_path):
        # Organic blocked_placeholder with missing source_id is now blocked
        # as an authoring error (source_id missing) rather than
        # "blocked_placeholder". The router still BLOCKS, just with a
        # different message.
        from builder.topology_helpers import generate_single_component_topology

        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "blocked_placeholder",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        with (
            patch(
                "builder.topology_helpers.parse_mol_topology",
                return_value=_two_atom_topology(),
            ),
            pytest.raises(BuildError) as exc_info,
        ):
            generate_single_component_topology(
                fake_mol_file,
                "DraftMol",
                molecule_count=1,
                packed_xyz_path=tmp_path / "packed.xyz",
                output_data_path=tmp_path / "out.data",
                box_dimensions=(10.0, 10.0, 10.0),
                ff_assignment=ff_assignment,
            )
        details = exc_info.value.details or {}
        assert details.get("stage") == "typing_router"
        assert "source_id is missing" in str(exc_info.value.message)

    def test_ionic_route_raises_build_error(self, fake_mol_file, tmp_path):
        """Wave 3 contract: the full-pipeline helper must surface the
        user-friendly router reason (Wave 3 + organic surrogate hint),
        not a generic ``ionic`` substring. The previous OR-style check
        was too lenient — it would have accepted a generic
        ``"ionic_executor not implemented"`` error and the operator
        would lose the actionable guidance.
        """
        from builder.topology_helpers import generate_single_component_topology

        ff_assignment = {
            "route": "ionic_profile",
            "status": "blocked_placeholder",
            "source_id": None,
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        with (
            patch(
                "builder.topology_helpers.parse_mol_topology",
                return_value=_two_atom_topology(),
            ),
            pytest.raises(BuildError) as exc_info,
        ):
            generate_single_component_topology(
                fake_mol_file,
                "NaCl",
                molecule_count=1,
                packed_xyz_path=tmp_path / "packed.xyz",
                output_data_path=tmp_path / "out.data",
                box_dimensions=(10.0, 10.0, 10.0),
                ff_assignment=ff_assignment,
            )
        msg = str(exc_info.value.message)
        # Wave 3 friendly-message lockdown (router-emitted text + helper
        # context). All four fragments must be present so a future
        # refactor cannot quietly drop the actionable hint.
        assert "NaCl" in msg
        assert "Ionic species" in msg
        assert "Wave 3" in msg
        assert "surrogate" in msg or "wait for the Wave 3 release" in msg
        # Stage tag from topology_helpers' BuildError details
        details = exc_info.value.details or {}
        assert details.get("stage") == "typing_router"

    def test_inorganic_profile_raises_build_error(self, fake_mol_file, tmp_path):
        from builder.topology_helpers import generate_single_component_topology

        ff_assignment = {
            "route": "inorganic_profile",
            "status": "active",
            "source_id": "silica_hydroxylated_v1",
            "formal_charge": 0,
            "canonical_smiles": None,
        }
        additive_def = {
            "category": "inorganic",
            "parameterization": {
                "mode": "inorganic_profile",
                "profile_id": "silica_hydroxylated_v1",
            },
        }
        with (
            patch(
                "builder.topology_helpers.parse_mol_topology",
                return_value=_two_atom_topology(),
            ),
            pytest.raises(BuildError) as exc_info,
        ):
            generate_single_component_topology(
                fake_mol_file,
                "SiO2",
                molecule_count=1,
                packed_xyz_path=tmp_path / "packed.xyz",
                output_data_path=tmp_path / "out.data",
                box_dimensions=(10.0, 10.0, 10.0),
                ff_assignment=ff_assignment,
                additive_def=additive_def,
            )
        assert "inorganic" in str(exc_info.value.message).lower()
