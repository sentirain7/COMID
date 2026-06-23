"""Test LJ parameter completeness in artifacts (fail-closed policy v00.99.29).

These tests verify that:
1. Test fixtures contain complete LJ parameters (epsilon/sigma)
2. Repo artifacts (if present) contain complete LJ parameters
3. Incomplete artifacts are properly detected by _is_artifact_complete()
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_ARTIFACT_DIR = _PROJECT_ROOT / "tests" / "data" / "forcefield_artifacts" / "organic_gaff2"
_REPO_ARTIFACT_DIR = _PROJECT_ROOT / "data" / "forcefield_artifacts" / "organic_gaff2"


def _check_artifact_lj_complete(artifact_path: Path) -> tuple[bool, list[str]]:
    """Check if artifact has complete LJ parameters (epsilon/sigma).

    Returns:
        (is_complete, missing_atoms) where missing_atoms lists atom indices missing LJ.
    """
    data = json.loads(artifact_path.read_text())
    atoms = data.get("atoms", [])
    missing = []

    for atom in atoms:
        idx = atom.get("index", "?")
        if "epsilon" not in atom or "sigma" not in atom:
            missing.append(str(idx))
        elif atom.get("epsilon") is None or atom.get("sigma") is None:
            missing.append(str(idx))

    return len(missing) == 0, missing


class TestFixtureArtifactsHaveLJ:
    """Test fixtures must have complete LJ parameters."""

    def test_fixture_artifacts_directory_exists(self):
        """Test fixture artifact directory exists."""
        if not _FIXTURE_ARTIFACT_DIR.exists():
            pytest.skip("Fixture artifact directory not found")
        assert _FIXTURE_ARTIFACT_DIR.is_dir()

    def test_toluene_fixture_has_lj(self):
        """Toluene fixture must have epsilon/sigma for all atoms."""
        toluene_path = _FIXTURE_ARTIFACT_DIR / "Toluene.json"
        if not toluene_path.exists():
            pytest.skip("Toluene fixture not available")

        is_complete, missing = _check_artifact_lj_complete(toluene_path)
        assert is_complete, f"Toluene fixture missing LJ for atoms: {missing}"

    def test_all_fixture_artifacts_have_lj(self):
        """All fixture artifacts must have complete LJ parameters."""
        if not _FIXTURE_ARTIFACT_DIR.exists():
            pytest.skip("Fixture artifact directory not found")

        artifacts = list(_FIXTURE_ARTIFACT_DIR.glob("*.json"))
        if not artifacts:
            pytest.skip("No fixture artifacts found")

        incomplete = []
        for art_path in artifacts:
            is_complete, missing = _check_artifact_lj_complete(art_path)
            if not is_complete:
                incomplete.append(f"{art_path.name}: atoms {missing}")

        assert not incomplete, "Incomplete fixture artifacts:\n" + "\n".join(incomplete)


class TestRepoArtifactsHaveLJ:
    """Repo artifacts (if present) must have complete LJ parameters."""

    def test_repo_artifacts_lj_complete_if_present(self):
        """Repo artifacts must have LJ if they exist."""
        if not _REPO_ARTIFACT_DIR.exists():
            pytest.skip("Repo artifact directory not found (expected for empty catalog)")

        artifacts = list(_REPO_ARTIFACT_DIR.glob("*.json"))
        if not artifacts:
            pytest.skip("No repo artifacts present (empty catalog)")

        incomplete = []
        for art_path in artifacts:
            is_complete, missing = _check_artifact_lj_complete(art_path)
            if not is_complete:
                incomplete.append(f"{art_path.name}: atoms {missing}")

        assert not incomplete, (
            "Incomplete repo artifacts violate fail-closed policy:\n" + "\n".join(incomplete)
        )


class TestIsArtifactCompleteFunction:
    """Test _is_artifact_complete() helper function."""

    def test_complete_artifact_returns_true(self):
        """Complete artifact should return True."""
        from features.molecules.artifact_service import _is_artifact_complete

        toluene_path = _FIXTURE_ARTIFACT_DIR / "Toluene.json"
        if not toluene_path.exists():
            pytest.skip("Toluene fixture not available")

        assert _is_artifact_complete(toluene_path) is True

    def test_nonexistent_artifact_returns_false(self, tmp_path):
        """Non-existent artifact should return False."""
        from features.molecules.artifact_service import _is_artifact_complete

        fake_path = tmp_path / "nonexistent.json"
        assert _is_artifact_complete(fake_path) is False

    def test_artifact_without_lj_returns_false(self, tmp_path):
        """Artifact without LJ parameters should return False."""
        from features.molecules.artifact_service import _is_artifact_complete

        incomplete = {
            "schema_version": 2,
            "ff_family": "organic_gaff2",
            "mol_id": "Test",
            "atoms": [
                {"index": 1, "element": "C", "ff_type": "c3", "charge": 0.0},
                # Missing epsilon/sigma
            ],
            "bond_types": [],
            "angle_types": [],
        }
        incomplete_path = tmp_path / "incomplete.json"
        incomplete_path.write_text(json.dumps(incomplete))

        assert _is_artifact_complete(incomplete_path) is False

    def test_artifact_with_complete_lj_returns_true(self, tmp_path):
        """Artifact with complete LJ parameters should return True."""
        from features.molecules.artifact_service import _is_artifact_complete

        complete = {
            "schema_version": 2,
            "ff_family": "organic_gaff2",
            "mol_id": "Test",
            "atoms": [
                {
                    "index": 1,
                    "element": "C",
                    "ff_type": "c3",
                    "charge": 0.0,
                    "epsilon": 0.1094,
                    "sigma": 3.3997,
                },
            ],
            "bond_types": [{"type": 1, "k": 300.0, "r0": 1.5}],
            "angle_types": [],
        }
        complete_path = tmp_path / "complete.json"
        complete_path.write_text(json.dumps(complete))

        assert _is_artifact_complete(complete_path) is True
