"""One-shot recovery: delete the dead bulk binder-cell grid and resubmit it fresh.

Context (2026-06-16): after the GPU0 removal (phantom GPU 6) + stall-checker
false-positive bugs, the entire 324-combo bulk grid
(3 binders x 3 aging x 3 additives x 12 temps) ended up failed/orphaned.
Root causes are fixed (settings.json auto-detect GPU + maintenance.py stall fix).
This script does the operational recovery the user approved:

    1. cancel  non-terminal grid experiments (queued/building/running)
    2. delete  ALL bulk-X1 grid experiments (full cascade)
    3. submit  the full grid fresh via the forward batch path

The single-molecule E_intra jobs (study_type='single_molecule_vacuum', completed)
are NOT touched. All recreate parameters were extracted from the existing grid
rows (not guessed) so the resubmission reproduces the original DOE exactly.

Run with the API up (POST endpoints used). Usage:
    python scripts/recreate_binder_cell_grid.py            # dry-run (counts only)
    python scripts/recreate_binder_cell_grid.py --apply    # execute
"""

from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request

API = "http://localhost:8000"
DB = "asphalt_agent.db"

# --- Recreate spec (extracted from the existing grid) -----------------------
BATCH_REQUEST = {
    "binder_types": ["AAA1", "AAK1", "AAM1"],
    "structure_sizes": ["X1"],
    "temperatures_k": [
        213.0, 233.0, 253.0, 273.0, 293.0, 313.0,
        333.0, 353.0, 373.0, 393.0, 413.0, 433.0,
    ],
    "aging_states": ["non_aging", "short_aging", "long_aging"],
    "tier": "screening",
    "ff_type": "bulk_ff_gaff2",
    "e_intra_method": "single_molecule_vacuum",
    # 'none' sentinel = control group; real additives zip 1:1 with concentrations
    "additive_types": ["none", "Lignin", "SiO2"],
    "additive_concentrations": [8.411699, 6.18443],  # Lignin, SiO2 (wt%)
    "initial_density": 0.2,
    "stage_requests": [
        {
            "stage_key": "high_temp_nvt",
            "enabled": True,
            "duration_ps": 100.0,
            "params_override": {"temperature_K": 500.0},
        },
        {
            "stage_key": "high_pressure_npt",
            "enabled": True,
            "duration_ps": 200.0,
            "params_override": {"temperature_K": 500.0, "pressure_atm": 100.0},
        },
        {"stage_key": "minimize", "enabled": True},
        {"stage_key": "nvt_equilibration", "enabled": True},
        {"stage_key": "npt_production", "enabled": True},
    ],
}

NON_TERMINAL = ("queued", "building", "running", "pending", "ready", "analyzing")


def _post(path: str, body: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _grid_ids(conn: sqlite3.Connection) -> tuple[list[str], list[str]]:
    """Return (all grid exp_ids, non-terminal exp_ids that need cancelling)."""
    rows = conn.execute(
        "SELECT exp_id, status FROM experiments "
        "WHERE study_type='bulk' AND structure_size='X1'"
    ).fetchall()
    all_ids = [r[0] for r in rows]
    cancel_ids = [r[0] for r in rows if r[1] in NON_TERMINAL]
    return all_ids, cancel_ids


def main() -> int:
    apply = "--apply" in sys.argv
    conn = sqlite3.connect(DB)
    all_ids, cancel_ids = _grid_ids(conn)
    conn.close()

    print(f"grid experiments (bulk X1): {len(all_ids)}")
    print(f"  non-terminal needing cancel: {len(cancel_ids)}")
    print("batch resubmit would create: 3 x 1 x 12 x 3 x 3 = 324 combos")

    if not apply:
        print("\nDRY-RUN. Re-run with --apply to cancel + delete + resubmit.")
        return 0

    if cancel_ids:
        print(f"\n[1/3] cancelling {len(cancel_ids)} non-terminal...")
        res = _post("/experiments/batch/cancel", {"exp_ids": cancel_ids})
        print("  cancel:", {k: res.get(k) for k in ("total", "succeeded", "skipped", "failed")})

    if all_ids:
        print(f"\n[2/3] deleting {len(all_ids)} grid experiments...")
        res = _post("/experiments/batch/delete", {"exp_ids": all_ids})
        print("  delete:", {k: res.get(k) for k in ("total", "succeeded", "skipped", "failed")})
        bad = [d for d in res.get("details", []) if not d.get("success")][:8]
        for d in bad:
            print("    skip:", d.get("exp_id"), "->", d.get("reason"))

    print("\n[3/3] submitting fresh grid via /batch-job/binder-cell ...")
    res = _post("/batch-job/binder-cell", BATCH_REQUEST)
    jobs = res.get("jobs", [])
    print(f"  submitted jobs: {len(jobs)}")
    print(f"  response keys: {list(res.keys())}")
    if res.get("ff_blocked_items"):
        print("  FF-blocked:", res["ff_blocked_items"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
