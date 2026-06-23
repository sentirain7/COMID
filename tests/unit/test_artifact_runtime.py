"""Regression tests for curated artifact runtime orchestration.

Covers:
- Fast path (existing complete artifact returns immediately).
- Slow path: missing artifact → generate_gaff2_artifact invoked → returns.
- Stale / incomplete artifact regenerated and log line emitted.
- Failure modes: mol_path absent → ArtifactMissingError; generation still
  incomplete → ArtifactIncompleteError.
- Concurrency: a single fcntl writer across concurrent callers.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from features.molecules.artifact_runtime import ensure_organic_artifact
from features.molecules.artifact_service import _is_artifact_complete


def _complete_artifact_payload(mol_id: str = "TestMol") -> dict:
    return {
        "schema_version": 2,
        "ff_family": "organic_gaff2",
        "charge_model": "am1_bcc",
        "mol_id": mol_id,
        "generator": "test",
        "generator_version": "1.0",
        "provenance": "test fixture",
        "canonical_smiles": "CC",
        "formal_charge": 0,
        "topology_hash": "",
        "charge_sum": 0.0,
        "atoms": [
            {
                "index": 1,
                "element": "C",
                "ff_type": "c3",
                "charge": 0.096,
                "epsilon": 0.1094,
                "sigma": 3.3997,
            },
            {
                "index": 2,
                "element": "H",
                "ff_type": "hc",
                "charge": -0.096,
                "epsilon": 0.0157,
                "sigma": 2.6495,
            },
        ],
        "bond_types": [{"key": "c3-hc", "k": 340.0, "r0": 1.09}],
        "angle_types": [],
        "dihedral_types": [],
        "improper_types": [],
    }


def _stale_artifact_payload() -> dict:
    payload = _complete_artifact_payload()
    # Break charge sum to force a rejection.
    payload["charge_sum"] = 0.004
    payload["atoms"][0]["charge"] = 0.100
    return payload


def _incomplete_artifact_payload(mol_id: str = "TestMol") -> dict:
    """Artifact with bond/charge sane but missing LJ params."""
    return {
        "schema_version": 2,
        "ff_family": "organic_gaff2",
        "mol_id": mol_id,
        "formal_charge": 0,
        "charge_sum": 0.0,
        "atoms": [
            {"index": 1, "element": "C", "ff_type": "c3", "charge": 0.0},
        ],
        "bond_types": [{"key": "c3-c3", "k": 300.0, "r0": 1.5}],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


@pytest.fixture
def artifact_env(tmp_path, monkeypatch):
    """Redirect artifact_service.get_artifact_path to tmp_path."""
    artifact_dir = tmp_path / "organic_gaff2"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "TestMol.json"

    def _fake_get_artifact_path(mol_id, ff_assignment=None):
        from features.molecules.artifact_service import resolve_artifact_source_id

        source_id = resolve_artifact_source_id(mol_id, ff_assignment)
        return artifact_dir / f"{source_id}.json"

    monkeypatch.setattr(
        "features.molecules.artifact_service.get_artifact_path",
        _fake_get_artifact_path,
    )
    return {"dir": artifact_dir, "path": artifact_path}


def test_is_artifact_complete_rejects_charge_mismatch(tmp_path):
    artifact_path = tmp_path / "organic_gaff2" / "TestMol.json"
    _write_json(artifact_path, _stale_artifact_payload())

    assert _is_artifact_complete(artifact_path) is False


def test_fast_path_returns_when_complete(artifact_env, tmp_path, monkeypatch):
    _write_json(artifact_env["path"], _complete_artifact_payload())
    mol_path = tmp_path / "TestMol.mol"
    mol_path.write_text("stub")

    called = {"count": 0}

    def _fail_if_called(**kwargs):
        called["count"] += 1
        raise AssertionError("generate_gaff2_artifact must not be called on fast path")

    monkeypatch.setattr(
        "features.molecules.artifact_service.generate_gaff2_artifact",
        _fail_if_called,
    )

    source_id = ensure_organic_artifact(
        mol_id="TestMol",
        mol_path=mol_path,
        ff_assignment={"source_id": "TestMol", "formal_charge": 0},
        ff_family="organic_gaff2",
    )
    assert source_id == "TestMol"
    assert called["count"] == 0


def test_generates_when_missing(artifact_env, tmp_path, monkeypatch, caplog):
    mol_path = tmp_path / "TestMol.mol"
    mol_path.write_text("stub")
    calls = {"count": 0}

    def _mock_generate(**kwargs):
        calls["count"] += 1
        payload = _complete_artifact_payload(kwargs["mol_id"])
        _write_json(artifact_env["path"], payload)
        return payload

    monkeypatch.setattr(
        "features.molecules.artifact_service.generate_gaff2_artifact",
        _mock_generate,
    )

    with caplog.at_level("INFO"):
        source_id = ensure_organic_artifact(
            mol_id="TestMol",
            mol_path=mol_path,
            ff_assignment={"source_id": "TestMol", "formal_charge": 0},
            ff_family="organic_gaff2",
        )

    assert source_id == "TestMol"
    assert calls["count"] == 1
    assert artifact_env["path"].exists()
    assert _is_artifact_complete(artifact_env["path"]) is True
    assert "Auto-generating GAFF2 artifact for TestMol" in caplog.text
    assert "Auto-generated GAFF2 artifact: TestMol" in caplog.text
    # v00.99.42: the lock marker intentionally persists on normal exit
    # (inode-stability invariant). Stale cleanup is the only removal
    # path. The fcntl lock itself is released — that is what matters
    # for correctness.
    assert (artifact_env["dir"] / ".TestMol.generating.lock").exists()


def test_regenerates_stale_charge_artifact(artifact_env, tmp_path, monkeypatch, caplog):
    _write_json(artifact_env["path"], _stale_artifact_payload())
    mol_path = tmp_path / "TestMol.mol"
    mol_path.write_text("stub")

    def _mock_generate(**kwargs):
        payload = _complete_artifact_payload(kwargs["mol_id"])
        _write_json(artifact_env["path"], payload)
        return payload

    monkeypatch.setattr(
        "features.molecules.artifact_service.generate_gaff2_artifact",
        _mock_generate,
    )

    with caplog.at_level("INFO"):
        source_id = ensure_organic_artifact(
            mol_id="TestMol",
            mol_path=mol_path,
            ff_assignment={"source_id": "TestMol", "formal_charge": 0},
            ff_family="organic_gaff2",
        )

    assert source_id == "TestMol"
    assert _is_artifact_complete(artifact_env["path"]) is True
    assert "rejected" in caplog.text.lower()
    assert "Auto-generated GAFF2 artifact: TestMol" in caplog.text


def test_raises_when_mol_missing(artifact_env, tmp_path, monkeypatch):
    mol_path = tmp_path / "does_not_exist.mol"  # not created

    def _unexpected(**kwargs):
        raise AssertionError("generate_gaff2_artifact must not be reached")

    monkeypatch.setattr(
        "features.molecules.artifact_service.generate_gaff2_artifact",
        _unexpected,
    )

    from forcefield.organic_curated_artifact import ArtifactMissingError

    with pytest.raises(ArtifactMissingError):
        ensure_organic_artifact(
            mol_id="TestMol",
            mol_path=mol_path,
            ff_assignment={"source_id": "TestMol", "formal_charge": 0},
            ff_family="organic_gaff2",
        )


def test_raises_when_generation_yields_incomplete(artifact_env, tmp_path, monkeypatch):
    mol_path = tmp_path / "TestMol.mol"
    mol_path.write_text("stub")

    def _mock_generate(**kwargs):
        # Write an incomplete artifact (no LJ params).
        _write_json(artifact_env["path"], _incomplete_artifact_payload(kwargs["mol_id"]))
        return _incomplete_artifact_payload(kwargs["mol_id"])

    monkeypatch.setattr(
        "features.molecules.artifact_service.generate_gaff2_artifact",
        _mock_generate,
    )

    from forcefield.organic_curated_artifact import ArtifactIncompleteError

    with pytest.raises(ArtifactIncompleteError):
        ensure_organic_artifact(
            mol_id="TestMol",
            mol_path=mol_path,
            ff_assignment={"source_id": "TestMol", "formal_charge": 0},
            ff_family="organic_gaff2",
        )


def test_progress_callback_forwarded_on_slow_path(artifact_env, tmp_path, monkeypatch):
    """slow path: progress_callback must reach generate_gaff2_artifact kwargs."""
    mol_path = tmp_path / "TestMol.mol"
    mol_path.write_text("stub")

    received: dict[str, object] = {}

    def _mock_generate(**kwargs):
        received.update(kwargs)
        _write_json(artifact_env["path"], _complete_artifact_payload(kwargs["mol_id"]))

    monkeypatch.setattr(
        "features.molecules.artifact_service.generate_gaff2_artifact",
        _mock_generate,
    )

    sentinel = lambda code, label: None  # noqa: E731 — test-local marker
    ensure_organic_artifact(
        mol_id="TestMol",
        mol_path=mol_path,
        ff_assignment={"source_id": "TestMol", "formal_charge": 0},
        ff_family="organic_gaff2",
        progress_callback=sentinel,
    )
    assert received.get("progress_callback") is sentinel


def test_progress_callback_not_called_on_fast_path(artifact_env, tmp_path, monkeypatch):
    """fast path: existing complete artifact skips generate → callback unused."""
    _write_json(artifact_env["path"], _complete_artifact_payload())
    mol_path = tmp_path / "TestMol.mol"
    mol_path.write_text("stub")

    def _unexpected(**_kwargs):
        raise AssertionError("generate_gaff2_artifact must not be called on fast path")

    monkeypatch.setattr(
        "features.molecules.artifact_service.generate_gaff2_artifact",
        _unexpected,
    )

    calls: list[tuple[str, str]] = []

    def _cb(code, label):
        calls.append((code, label))

    source_id = ensure_organic_artifact(
        mol_id="TestMol",
        mol_path=mol_path,
        ff_assignment={"source_id": "TestMol", "formal_charge": 0},
        ff_family="organic_gaff2",
        progress_callback=_cb,
    )
    assert source_id == "TestMol"
    assert calls == []


def test_concurrent_callers_invoke_generate_once(artifact_env, tmp_path, monkeypatch):
    mol_path = tmp_path / "TestMol.mol"
    mol_path.write_text("stub")
    call_count = {"n": 0}
    lock = threading.Lock()
    start = threading.Event()

    def _mock_generate(**kwargs):
        with lock:
            call_count["n"] += 1
        # Simulate some work so the other thread is forced to wait on the
        # fcntl lock.
        start.wait(timeout=0.5)
        payload = _complete_artifact_payload(kwargs["mol_id"])
        _write_json(artifact_env["path"], payload)
        return payload

    monkeypatch.setattr(
        "features.molecules.artifact_service.generate_gaff2_artifact",
        _mock_generate,
    )

    results: list[str] = []
    errors: list[BaseException] = []

    def _worker():
        try:
            sid = ensure_organic_artifact(
                mol_id="TestMol",
                mol_path=mol_path,
                ff_assignment={"source_id": "TestMol", "formal_charge": 0},
                ff_family="organic_gaff2",
            )
            results.append(sid)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    # Let workers queue up, then release the mock generator.
    start.set()
    for t in threads:
        t.join(timeout=5)

    assert not errors, f"worker errors: {errors}"
    assert results == ["TestMol"] * 4
    # Only the first writer should have called generate_gaff2_artifact;
    # the rest should have taken the lock-double-check fast path.
    assert call_count["n"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# v00.99.42 reinforcement — cleanup_stale_artifact_locks dead-import fix
# ─────────────────────────────────────────────────────────────────────────────


def test_cleanup_stale_artifact_locks_default_dir_smoke(tmp_path, monkeypatch):
    """Calling with artifact_dir=None must not blow up on a dead import.

    Pre-fix this raised ``ImportError: cannot import name '_get_artifact_base_dir'``
    because that helper was never defined in artifact_service.
    """
    from features.molecules import artifact_service
    from features.molecules.artifact_runtime import cleanup_stale_artifact_locks

    monkeypatch.setattr(artifact_service, "ARTIFACT_DIR", tmp_path)
    # No lock files exist; should return 0 without raising.
    assert cleanup_stale_artifact_locks(None, threshold_hours=1.0) == 0
