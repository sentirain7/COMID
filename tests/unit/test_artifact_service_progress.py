"""Unit tests for generate_gaff2_artifact progress callback (v00.99.30).

Verifies that the four FF parameter generation stages emit progress events in
order: antechamber → parmchk2 → tleap → parmed. AmberTools (antechamber/
parmchk2/tleap) and parmed are monkeypatched so the test runs in any
environment.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


class _FakeAtomType:
    def __init__(self, epsilon=0.1094, sigma=3.3997):
        self.epsilon = epsilon
        self.sigma = sigma


class _FakeAtom:
    def __init__(self, idx, element, type_, charge):
        self.idx = idx
        self.element_name = element
        self.type = type_
        self.charge = charge
        self.epsilon = 0.1094
        self.sigma = 3.3997
        self.atom_type = _FakeAtomType()


class _FakeBondType:
    def __init__(self, k=300.0, req=1.5):
        self.k = k
        self.req = req


class _FakeBond:
    def __init__(self, a, b, k=300.0, req=1.5):
        self.atom1 = a
        self.atom2 = b
        self.type = _FakeBondType(k, req)


class _FakeParm:
    """Minimal parmed-like structure for the artifact extraction loop."""

    def __init__(self):
        a = _FakeAtom(0, "C", "c3", 0.0)
        b = _FakeAtom(1, "H", "hc", 0.0)
        self.atoms = [a, b]
        self.bonds = [_FakeBond(a, b)]
        self.angles = []
        self.dihedrals = []
        self.impropers = []


@pytest.fixture
def patched_artifact_env(tmp_path, monkeypatch):
    """Redirect artifact directory + stub out AmberTools + parmed."""

    import features.molecules.artifact_service as svc

    # Redirect output artifact dir into tmp_path so tests don't pollute repo.
    monkeypatch.setattr(svc, "ARTIFACT_DIR", tmp_path / "organic_gaff2")

    # Simulate successful antechamber / parmchk2 / tleap by:
    #  1. Returning a fake CompletedProcess with returncode 0.
    #  2. Creating the output files that the real binaries would have made.
    call_log: list[tuple[str, ...]] = []

    def _fake_helper(cmd, *, cwd=None, timeout=None, stage_name="", mol_id="", env=None):
        prog = cmd[0]
        call_log.append(tuple(cmd))
        wd = Path(cwd) if cwd else Path.cwd()
        if prog == "antechamber":
            out_idx = cmd.index("-o") + 1
            Path(cmd[out_idx]).touch()
        elif prog == "parmchk2":
            out_idx = cmd.index("-o") + 1
            Path(cmd[out_idx]).touch()
        elif prog == "tleap":
            (wd / "sys.prmtop").touch()
            (wd / "sys.inpcrd").touch()
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(svc, "_run_subprocess_with_group_kill", _fake_helper)

    # Stub parmed.load_file → _FakeParm and make module importable.
    fake_parmed = types.SimpleNamespace(load_file=lambda *a, **k: _FakeParm())
    monkeypatch.setitem(sys.modules, "parmed", fake_parmed)

    # Stub charge normaliser to be a no-op passthrough.
    monkeypatch.setattr(
        svc,
        "_normalize_artifact_atom_charges",
        lambda atoms, formal_charge: (atoms, 0.0),
    )

    return svc, call_log


class TestGenerateGaff2ArtifactProgress:
    """Four-stage progress callback contract."""

    def test_emits_four_stages_in_order(self, patched_artifact_env, tmp_path):
        svc, _ = patched_artifact_env
        mol_path = tmp_path / "TestMol.mol"
        mol_path.write_text("stub")

        callback = MagicMock()
        svc.generate_gaff2_artifact(
            mol_path=mol_path,
            mol_id="TestMol",
            smiles="CC",
            formal_charge=0,
            progress_callback=callback,
        )

        assert callback.call_count == 4
        codes = [c.args[0] for c in callback.call_args_list]
        assert codes == [
            "artifact_antechamber",
            "artifact_parmchk2",
            "artifact_tleap",
            "artifact_parmed",
        ]
        # Labels are Korean human-readable strings with subprocess name in parens.
        labels = [c.args[1] for c in callback.call_args_list]
        assert "antechamber" in labels[0]
        assert "parmchk2" in labels[1]
        assert "tleap" in labels[2]
        assert "parmed" in labels[3]

    def test_progress_callback_none_is_allowed(self, patched_artifact_env, tmp_path):
        """Passing progress_callback=None must not raise."""
        svc, _ = patched_artifact_env
        mol_path = tmp_path / "Mol.mol"
        mol_path.write_text("stub")
        svc.generate_gaff2_artifact(
            mol_path=mol_path,
            mol_id="Mol",
            progress_callback=None,
        )
        # Artifact JSON should have been written to the redirected dir.
        out_path = svc.ARTIFACT_DIR / "Mol.json"
        assert out_path.exists()
        payload = json.loads(out_path.read_text())
        assert payload["mol_id"] == "Mol"

    def test_progress_callback_exception_is_swallowed(self, patched_artifact_env, tmp_path):
        """Callback exceptions must not break the build."""
        svc, _ = patched_artifact_env
        mol_path = tmp_path / "Mol.mol"
        mol_path.write_text("stub")

        def _explode(code, label):
            raise RuntimeError("telemetry down")

        # Should complete despite the callback raising on each stage.
        svc.generate_gaff2_artifact(mol_path=mol_path, mol_id="Mol", progress_callback=_explode)
        assert (svc.ARTIFACT_DIR / "Mol.json").exists()
