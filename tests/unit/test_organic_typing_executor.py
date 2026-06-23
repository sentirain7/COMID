"""GAFF2 dispatcher regression for organic_typing_executor (curated artifact only)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from forcefield.organic_curated_artifact import (  # noqa: E402
    clear_artifact_cache,
)
from forcefield.organic_typing_executor import (  # noqa: E402
    OrganicAssignmentError,
    OrganicAssignmentResult,
    assign_organic,
)
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


def _toluene_topology() -> SimpleNamespace:
    """Build a 15-atom topology shaped exactly like the Toluene fixture."""
    elements = (
        # methyl group
        ["C", "H", "H", "H"]
        # aromatic ring
        + ["C", "C", "C", "C", "C", "C"]
        + ["H", "H", "H", "H", "H"]
    )
    return SimpleNamespace(
        mol_id="Toluene",
        atoms=[
            SimpleNamespace(
                index=i + 1,
                element=elements[i],
                ff_type="",
                charge=0.0,
                charge_defined=False,
            )
            for i in range(15)
        ],
    )


def _two_atom_topology() -> SimpleNamespace:
    return SimpleNamespace(
        mol_id="MockMol",
        atoms=[
            SimpleNamespace(index=1, element="C", ff_type="", charge=0.0, charge_defined=False),
            SimpleNamespace(index=2, element="H", ff_type="", charge=0.0, charge_defined=False),
        ],
    )


class TestArtifactRoute:
    def test_artifact_route_applies_curated_artifact(self, tmp_path):
        topology = _toluene_topology()
        result = assign_organic(
            topology=topology,
            mol_file=tmp_path / "Toluene.mol",
            strategy=TypingStrategy.ORGANIC_CURATED_ARTIFACT,
            source_id="Toluene",
            ff_family="organic_gaff2",
        )
        assert isinstance(result, OrganicAssignmentResult)
        assert result.charge_model == GAFF2_ARTIFACT_LABEL
        assert result.artifact is not None
        assert result.artifact.mol_id == "Toluene"
        assert result.cache_key == "organic_gaff2_artifact:Toluene"

        # Topology should now carry the curated ff_types and charges.
        assert all(atom.charge_defined for atom in topology.atoms)

    def test_artifact_route_reports_cache_hit_on_second_call(self, tmp_path):
        first_topology = _toluene_topology()
        first = assign_organic(
            topology=first_topology,
            mol_file=tmp_path / "Toluene.mol",
            strategy=TypingStrategy.ORGANIC_CURATED_ARTIFACT,
            source_id="Toluene",
            ff_family="organic_gaff2",
        )
        # First call is a miss in the in-memory cache.
        assert first.cache_hit is False

        second_topology = _toluene_topology()
        second = assign_organic(
            topology=second_topology,
            mol_file=tmp_path / "Toluene.mol",
            strategy=TypingStrategy.ORGANIC_CURATED_ARTIFACT,
            source_id="Toluene",
            ff_family="organic_gaff2",
        )
        assert second.cache_hit is True
        assert second.charge_model == GAFF2_ARTIFACT_LABEL

    def test_missing_artifact_raises_organic_assignment_error(self, tmp_path):
        topology = _two_atom_topology()
        with pytest.raises(OrganicAssignmentError) as exc_info:
            assign_organic(
                topology=topology,
                mol_file=tmp_path / "Mystery.mol",
                strategy=TypingStrategy.ORGANIC_CURATED_ARTIFACT,
                source_id="Mystery_does_not_exist_xyz",
            )
        assert "missing" in str(exc_info.value).lower()
        details = exc_info.value.details
        assert details.get("source_id") == "Mystery_does_not_exist_xyz"
        assert details.get("stage") == "artifact_load"

    def test_artifact_route_without_source_id_fails_closed(self, tmp_path):
        topology = _two_atom_topology()
        with pytest.raises(OrganicAssignmentError, match="source_id is missing"):
            assign_organic(
                topology=topology,
                mol_file=tmp_path / "Mystery.mol",
                strategy=TypingStrategy.ORGANIC_CURATED_ARTIFACT,
                source_id=None,
            )
        # Topology must NOT have been mutated by a half-applied artifact.
        assert topology.atoms[0].ff_type == ""
        assert topology.atoms[0].charge_defined is False


class TestStrategyGuard:
    def test_non_organic_strategy_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="non-organic"):
            assign_organic(
                topology=_two_atom_topology(),
                mol_file=tmp_path / "x.mol",
                strategy=TypingStrategy.INORGANIC_PROFILE,
                source_id=None,
            )

    def test_blocked_strategy_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="non-organic"):
            assign_organic(
                topology=_two_atom_topology(),
                mol_file=tmp_path / "x.mol",
                strategy=TypingStrategy.BLOCKED,
                source_id=None,
            )

    def test_ionic_strategy_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="non-organic"):
            assign_organic(
                topology=_two_atom_topology(),
                mol_file=tmp_path / "x.mol",
                strategy=TypingStrategy.IONIC_PROFILE,
                source_id=None,
            )
