"""v00.99.72 — probe_single_component_generation_support observe_only contract.

Preview endpoints (GET /molecules/{id}/structure, GET /interface-molecules)
must never trigger synchronous AM1-BCC generation. The `observe_only=True`
argument routes the organic_curated_artifact branch through an on-disk
readiness check (:func:`is_artifact_ready`) instead of
:func:`ensure_organic_artifact`, which would block the thread pool on
antechamber/sqm for large molecules (Lignin 350 atoms → hours).

Build/submit paths keep the default ``observe_only=False`` so the
generation contract is unchanged.
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


@pytest.fixture
def fake_mol_file(tmp_path):
    f = tmp_path / "fake.mol"
    f.write_text("dummy")
    return f


def _topology():
    return SimpleNamespace(
        mol_id="ObsOnly",
        n_atoms=1,
        n_bonds=0,
        atoms=[
            SimpleNamespace(
                index=1,
                element="C",
                ff_type="",
                charge=0.0,
                charge_defined=False,
                x=0.0,
                y=0.0,
                z=0.0,
            )
        ],
        bonds=[],
    )


class TestObserveOnlyOrganicCuratedArtifact:
    """observe_only=True must short-circuit to is_artifact_ready and never
    call ensure_organic_artifact. This is the contract preview depends on."""

    def test_missing_artifact_returns_not_generated_without_triggering_generation(
        self, fake_mol_file
    ):
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "SomeOrganic",
            "formal_charge": 0,
            "canonical_smiles": "C",
        }
        with (
            patch(
                "builder.topology_helpers.parse_mol_topology",
                return_value=_topology(),
            ),
            patch(
                "features.molecules.artifact_runtime.is_artifact_ready",
                return_value=(False, "SomeOrganic"),
            ) as ready_mock,
            patch("features.molecules.artifact_runtime.ensure_organic_artifact") as ensure_mock,
        ):
            ok, reason = probe_single_component_generation_support(
                fake_mol_file,
                "SomeOrganic",
                ff_assignment=ff_assignment,
                observe_only=True,
            )
        assert ok is False
        assert "not generated" in (reason or "").lower()
        assert "SomeOrganic" in (reason or "")
        ready_mock.assert_called_once()
        # The key invariant: observe_only must never invoke generation.
        ensure_mock.assert_not_called()

    def test_ready_artifact_returns_supported_without_running_assign_organic(self, fake_mol_file):
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "SomeOrganic",
            "formal_charge": 0,
            "canonical_smiles": "C",
        }
        with (
            patch(
                "builder.topology_helpers.parse_mol_topology",
                return_value=_topology(),
            ),
            patch(
                "features.molecules.artifact_runtime.is_artifact_ready",
                return_value=(True, "SomeOrganic"),
            ),
            patch("features.molecules.artifact_runtime.ensure_organic_artifact") as ensure_mock,
            patch("builder.topology_helpers.assign_organic") as assign_mock,
        ):
            ok, reason = probe_single_component_generation_support(
                fake_mol_file,
                "SomeOrganic",
                ff_assignment=ff_assignment,
                observe_only=True,
            )
        assert ok is True
        assert reason is None
        ensure_mock.assert_not_called()
        # observe_only also skips assign_organic (which re-runs typing/charge
        # and can be expensive for large molecules) — readiness on disk is
        # sufficient signal for the preview UI's FF badge.
        assign_mock.assert_not_called()


class TestObserveOnlyDefault:
    """Build/submit callers depend on the default observe_only=False to
    retain the fail-closed ensure_organic_artifact behaviour."""

    def test_default_keeps_ensure_organic_artifact_path(self, fake_mol_file):
        ff_assignment = {
            "route": "organic_curated_artifact",
            "status": "active",
            "source_id": "SomeOrganic",
            "formal_charge": 0,
            "canonical_smiles": "C",
        }
        with (
            patch(
                "builder.topology_helpers.parse_mol_topology",
                return_value=_topology(),
            ),
            patch("features.molecules.artifact_runtime.is_artifact_ready") as ready_mock,
            patch(
                "features.molecules.artifact_runtime.ensure_organic_artifact",
                return_value="SomeOrganic",
            ) as ensure_mock,
            patch(
                "builder.topology_helpers.assign_organic",
                return_value=None,
            ),
            patch(
                "builder.topology_helpers.validate_molecule_topologies",
                return_value=None,
            ),
        ):
            ok, _reason = probe_single_component_generation_support(
                fake_mol_file,
                "SomeOrganic",
                ff_assignment=ff_assignment,
                # observe_only omitted → default False
            )
        # Default path goes through ensure_organic_artifact (build/submit
        # contract) and skips is_artifact_ready entirely.
        ensure_mock.assert_called_once()
        ready_mock.assert_not_called()
        assert ok is True
