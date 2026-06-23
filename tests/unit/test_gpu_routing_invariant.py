"""Invariant: GPU routing must use UUID, never a raw integer index.

Guards against regressing the CUDA MPS index-remapping bug (a non-contiguous
visible set is renumbered to logical 0..N-1, so routing a physical index like
"6" yields cudaErrorNoDevice and silently kills every job on that GPU). All
``CUDA_VISIBLE_DEVICES`` writes in production code must go through
``monitoring.gpu_collector.gpu_uuid_for``. See memory `gpu-uuid-routing-principle`.
"""

import re
from pathlib import Path

import pytest

from monitoring.gpu_collector import (
    clear_gpu_uuid_map_cache,
    detect_eligible_compute_gpus,
    enumerate_compute_devices,
    get_gpu_uuid_map,
    gpu_uuid_for,
    resolve_sharing_mode,
)

SRC = Path(__file__).resolve().parents[2] / "src"

# Assignment to CUDA_VISIBLE_DEVICES whose RHS derives from a raw gpu index.
_RAW_ROUTING = re.compile(
    r"""CUDA_VISIBLE_DEVICES["']\]?\s*[:=]\s*str\(""", re.VERBOSE
)


def _src_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "test" not in p.name]


def test_no_raw_index_cuda_visible_devices_assignment():
    """No production code sets CUDA_VISIBLE_DEVICES = str(<index>)."""
    offenders = []
    for py in _src_files():
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if "CUDA_VISIBLE_DEVICES" not in line:
                continue
            if _RAW_ROUTING.search(line) and "gpu_uuid_for" not in line:
                offenders.append(f"{py.relative_to(SRC)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "GPU routing must use gpu_uuid_for() (UUID), not a raw index — "
        "regresses the MPS remapping bug:\n" + "\n".join(offenders)
    )


def test_routing_sites_use_gpu_uuid_for():
    """The known GPU-launch sites route through gpu_uuid_for()."""
    for rel in ("orchestrator/lammps_runner.py", "orchestrator/lammps_probe.py"):
        text = (SRC / rel).read_text(encoding="utf-8")
        assert "gpu_uuid_for" in text, f"{rel} must route GPUs via gpu_uuid_for()"


def test_gpu_uuid_for_falls_back_without_gpu(monkeypatch):
    """Without nvidia-smi/devices, gpu_uuid_for falls back to str(id)."""
    clear_gpu_uuid_map_cache()
    monkeypatch.setattr(
        "monitoring.gpu_collector.enumerate_compute_devices", lambda *a, **k: []
    )
    try:
        assert gpu_uuid_for(0) == "0"
        assert gpu_uuid_for(5) == "5"
    finally:
        clear_gpu_uuid_map_cache()


def test_transient_empty_enumerate_not_cached(monkeypatch):
    """A transient nvidia-smi failure (empty result) must NOT poison the cache.

    Regression for the v01.06.14 incident: a fork worker that built its UUID map
    during an nvidia-smi glitch cached {} and routed every GPU via raw integer
    (CUDA_VISIBLE_DEVICES=6) for its whole life -> GPU idle + jobs failed under
    MPS. The empty build must be discarded so the next call rebuilds healthily.
    """
    calls = {"n": 0}
    full = [{"gpu_id": 0, "uuid": "GPU-aaa"}, {"gpu_id": 6, "uuid": "GPU-eee"}]
    seq = [[], full]  # first call transient-empty, then healthy

    def fake(*a, **k):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]

    monkeypatch.setattr("monitoring.gpu_collector.enumerate_compute_devices", fake)
    clear_gpu_uuid_map_cache()
    try:
        assert get_gpu_uuid_map() == {}  # empty result returned but NOT cached
        # next call rebuilds from the now-healthy enumeration
        assert get_gpu_uuid_map() == {0: "GPU-aaa", 6: "GPU-eee"}
        assert gpu_uuid_for(6) == "GPU-eee"  # UUID, never raw "6"
    finally:
        clear_gpu_uuid_map_cache()


def test_gpu_uuid_for_self_heals_stale_partial_map(monkeypatch):
    """A cached map missing a GPU the scheduler routes to triggers a one-shot
    rebuild before any raw-integer fallback (self-heal of a stale/partial cache)."""
    import monitoring.gpu_collector as gc

    full = [{"gpu_id": 0, "uuid": "GPU-aaa"}, {"gpu_id": 6, "uuid": "GPU-eee"}]
    monkeypatch.setattr(
        "monitoring.gpu_collector.enumerate_compute_devices", lambda *a, **k: full
    )
    clear_gpu_uuid_map_cache()
    try:
        # Simulate a stale partial cache (e.g. built before GPU 6 was enumerated).
        gc._GPU_UUID_MAP = {0: "GPU-aaa"}
        assert gpu_uuid_for(6) == "GPU-eee"  # rebuilds on miss, returns UUID
    finally:
        clear_gpu_uuid_map_cache()


def test_full_universe_keeps_raw_ids_and_maps_all_devices(monkeypatch):
    """The device registry keeps the nvidia-smi ids and the UUID map covers ALL
    devices — including a sub-threshold RTX 3050 and every H200 — so gpu_uuid_for
    never falls back for a real device.

    Regression guard for the two-numbering-scheme bug: renumbering the eligible
    subset to a gap-free 0..N-1 left the 3050 and the split-off H200 without a map
    entry, mislabeling GPUs and forcing the cudaErrorNoDevice raw fallback. Raw
    nvidia-smi indices are contiguous, so the mig-default sequential numbering
    equals them here (no MIG enabled -> whole-GPU devices).
    """
    fake = [
        {"gpu_id": 0, "uuid": "GPU-h0", "name": "H200", "memory_gb": 140.0},
        {"gpu_id": 1, "uuid": "GPU-h1", "name": "H200", "memory_gb": 140.0},
        {"gpu_id": 2, "uuid": "GPU-h2", "name": "H200", "memory_gb": 140.0},
        {"gpu_id": 3, "uuid": "GPU-h3", "name": "H200", "memory_gb": 140.0},
        {"gpu_id": 4, "uuid": "GPU-h4", "name": "H200", "memory_gb": 140.0},
        {"gpu_id": 5, "uuid": "GPU-3050", "name": "RTX 3050", "memory_gb": 6.0},
        {"gpu_id": 6, "uuid": "GPU-h6", "name": "H200", "memory_gb": 140.0},
    ]
    monkeypatch.setattr("monitoring.gpu_collector.detect_system_gpus", lambda: fake)
    # No MIG enabled -> whole-GPU devices (the RTX 3050 stays id 5, eligible=False).
    monkeypatch.setattr("monitoring.gpu_collector.detect_mig_instances", lambda: {})
    monkeypatch.setattr("monitoring.gpu_collector._mig_enabled_gpu_uuids", lambda: set())
    clear_gpu_uuid_map_cache()
    try:
        # eligible subset drops the 3050 (id 5), keeps the H200 ids unchanged.
        eligible = detect_eligible_compute_gpus(min_memory_gb=32.0)
        assert [g["gpu_id"] for g in eligible] == [0, 1, 2, 3, 4, 6]
        # full universe includes the 3050, each tagged with eligibility.
        devices = enumerate_compute_devices(min_memory_gb=32.0)
        assert [(d["gpu_id"], d["eligible"]) for d in devices] == [
            (0, True),
            (1, True),
            (2, True),
            (3, True),
            (4, True),
            (5, False),
            (6, True),
        ]
        # UUID map covers ALL devices -> the split-off H200 (id 6) and the 3050
        # (id 5) both route, no raw-index fallback.
        m = get_gpu_uuid_map()
        assert m[6] == "GPU-h6" and m[5] == "GPU-3050"
        assert gpu_uuid_for(6) == "GPU-h6"  # no fallback to "6"
        assert gpu_uuid_for(5) == "GPU-3050"  # 3050 routable if selected
    finally:
        clear_gpu_uuid_map_cache()


def test_detect_mig_instances_parses_nvidia_smi_l(monkeypatch):
    """detect_mig_instances parses `nvidia-smi -L` into {parent_uuid: [instances]}."""
    import monitoring.gpu_collector as gc

    sample = (
        "GPU 0: NVIDIA H200 NVL (UUID: GPU-aaa)\n"
        "  MIG 1g.18gb     Device  0: (UUID: MIG-0a)\n"
        "  MIG 1g.18gb     Device  1: (UUID: MIG-0b)\n"
        "GPU 5: NVIDIA GeForce RTX 3050 (UUID: GPU-3050)\n"
    )

    class _R:
        returncode = 0
        stdout = sample

    monkeypatch.setattr(gc.subprocess, "run", lambda *a, **k: _R())
    inst = gc.detect_mig_instances()
    assert inst == {
        "GPU-aaa": [
            {"profile": "1g.18gb", "uuid": "MIG-0a", "memory_gb": 18.0},
            {"profile": "1g.18gb", "uuid": "MIG-0b", "memory_gb": 18.0},
        ]
    }


def test_resolve_sharing_mode(monkeypatch):
    """auto -> mig when MIG present else none (NEVER mps); explicit modes pass."""
    monkeypatch.setattr("monitoring.gpu_collector.detect_mig_instances", lambda: {})
    assert resolve_sharing_mode("auto") == "none"  # no MIG -> none, not mps
    assert resolve_sharing_mode("mig") == "mig"
    assert resolve_sharing_mode("none") == "none"
    assert resolve_sharing_mode("mps") == "mps"  # deprecated but honored if explicit
    assert resolve_sharing_mode("garbage") == "mig"  # unknown -> default mig
    monkeypatch.setattr(
        "monitoring.gpu_collector.detect_mig_instances",
        lambda: {"GPU-x": [{"profile": "1g.18gb", "uuid": "MIG-x", "memory_gb": 18.0}]},
    )
    assert resolve_sharing_mode("auto") == "mig"


def test_mig_mode_enumerates_instances_as_devices(monkeypatch):
    """MIG mode: each MIG instance is a 1-slot device routed by MIG-UUID; a
    non-MIG GPU (RTX 3050) stays a whole device. logical ids are sequential."""
    from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY

    # gpu_uuid_for() builds the map from the policy-default mode; force mig so the
    # no-arg get_gpu_uuid_map() reflects MIG routing (default is mps).
    monkeypatch.setattr(DEFAULT_JOB_BUDGETING_POLICY, "gpu_sharing_mode", "mig")
    whole = [
        {"gpu_id": 0, "uuid": "GPU-h200a", "name": "NVIDIA H200 NVL", "memory_gb": 140.0},
        {"gpu_id": 5, "uuid": "GPU-3050", "name": "NVIDIA GeForce RTX 3050", "memory_gb": 6.0},
    ]
    mig = {
        "GPU-h200a": [
            {"profile": "1g.18gb", "uuid": "MIG-a0", "memory_gb": 18.0},
            {"profile": "1g.18gb", "uuid": "MIG-a1", "memory_gb": 18.0},
        ],
    }
    monkeypatch.setattr("monitoring.gpu_collector.detect_system_gpus", lambda: whole)
    monkeypatch.setattr("monitoring.gpu_collector.detect_mig_instances", lambda: mig)
    monkeypatch.setattr("monitoring.gpu_collector._mig_enabled_gpu_uuids", lambda: set())
    clear_gpu_uuid_map_cache()
    try:
        devices = enumerate_compute_devices(min_memory_gb=32.0, mode="mig")
        assert [
            (d["gpu_id"], d["kind"], d["uuid"], d["slots"], d["eligible"]) for d in devices
        ] == [
            (0, "mig_instance", "MIG-a0", 1, True),
            (1, "mig_instance", "MIG-a1", 1, True),
            (2, "whole_gpu", "GPU-3050", 1, False),
        ]
        assert devices[0]["parent_uuid"] == "GPU-h200a"
        # routing by MIG UUID (auto resolves to mig since detect_mig_instances is set)
        assert gpu_uuid_for(0) == "MIG-a0"
        assert gpu_uuid_for(1) == "MIG-a1"
        assert gpu_uuid_for(2) == "GPU-3050"
    finally:
        clear_gpu_uuid_map_cache()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
