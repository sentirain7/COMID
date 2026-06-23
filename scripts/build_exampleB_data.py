"""Build the two CSVs that back the Example B (CED-by-subtraction) figure.

Reads the git-tracked sidecars so the figure reproduces on ANY machine using
whatever data is present there (run this on the server to pick up ALL data):

  data/forcefield_artifacts/e_intra/*.json   -> exampleB_eintra_references.csv
  data/result_sidecars/*.json                -> exampleB_ced_labels.csv

If the server DB has completed runs not yet written as sidecars, first run the
backfill exporters so this picks them up:
  python scripts/export_e_intra_sidecars.py
  python scripts/export_result_sidecars.py

Usage: python scripts/build_exampleB_data.py
"""

import csv
import glob
import json
import os

EI_DIR = "data/forcefield_artifacts/e_intra"
CED_DIR = "data/result_sidecars"
OUT = "docs/figures"

# --- Figure-only data exclusions (the DB and sidecars are NEVER modified) ---
# (1) Whole molecule dropped from the E_intra reference panel: SiO2 is an
#     inorganic (ionic) cluster whose vacuum E_intra is large-negative
#     (~-8600 kcal/mol, e.g. -8566 @ 293 K) — a different physical scale that
#     dominates/stretches the organic-binder E_intra axis.
EI_EXCLUDE_MOLS = {"SiO2"}
# (2) Single corrupted (molecule, temperature) E_intra point(s):
#     SBS_3_7 @ 413 K = 409254 kcal/mol (~370x its other 11 temps, all ~1100).
BAD_POINTS = {("SBS_3_7", 413)}
# (3) Anomalously high CED labels dropped (graph only): SiO2-additive binders at
#     433 K give CED >= 470 MJ/m3 (~2x the non-SiO2 binders), tracing to the SiO2
#     vacuum-E_intra anomaly entering the CED subtraction.
CED_DROP_T, CED_DROP_MIN = 433.0, 470.0


def build_eintra(out_csv):
    rows, mols, temps = [], set(), set()
    dropped = []
    for f in sorted(glob.glob(f"{EI_DIR}/*.json")):
        d = json.load(open(f))
        mid = d["mol_id"]
        if mid in EI_EXCLUDE_MOLS:
            continue
        for e in d["entries"]:
            if (mid, int(round(e["temperature_K"]))) in BAD_POINTS:
                dropped.append((mid, e["temperature_K"], e["e_intra"]))
                continue
            rows.append({"mol_id": mid, "temperature_K": e["temperature_K"],
                         "e_intra_kcal_mol": e["e_intra"], "ff": e["ff_name"],
                         "method": e["method"]})
            mols.add(mid)
            temps.add(e["temperature_K"])
    for mid, t, v in dropped:
        print(f"  [dropped corrupted point] {mid} @ {t:.0f}K = {v:.1f} kcal/mol")
    with open(out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["mol_id", "temperature_K",
                                           "e_intra_kcal_mol", "ff", "method"])
        w.writeheader()
        w.writerows(rows)
    print(f"  E_intra refs: {len(mols)} molecules x {len(temps)} temps "
          f"= {len(rows)} rows  ->  {out_csv}")
    return sorted(temps)


def build_ced(out_csv):
    rows = []
    for f in sorted(glob.glob(f"{CED_DIR}/*.json")):
        d = json.load(open(f))
        ex = d["experiment"]
        ced = next((m for m in d["metrics"]
                    if m["metric_name"] == "cohesive_energy_density"), None)
        if ced is None:
            continue
        Tk = ex.get("temperature_K")
        if Tk is not None and abs(float(Tk) - CED_DROP_T) < 0.5 and float(ced["value"]) >= CED_DROP_MIN:
            print(f"  [dropped high CED] {ex['exp_id']} ({ex.get('additive_type')}) "
                  f"{Tk:.0f}K = {ced['value']:.1f} MJ/m3")
            continue
        v = ex.get("box_lx", 0) * ex.get("box_ly", 0) * ex.get("box_lz", 0)
        rows.append({
            "exp_id": ex["exp_id"], "binder_type": ex.get("binder_type"),
            "additive_type": ex.get("additive_type") or "none",
            "additive_wt": ex.get("additive_wt"), "aging_state": ex.get("aging_state"),
            "temperature_K": ex.get("temperature_K"),
            "ced_MJ_m3": ced["value"], "ced_uncertainty": ced["uncertainty"],
            "volume_A3": round(v, 2), "n_atoms": ex.get("actual_atoms"),
        })
    flds = ["exp_id", "binder_type", "additive_type", "additive_wt", "aging_state",
            "temperature_K", "ced_MJ_m3", "ced_uncertainty", "volume_A3", "n_atoms"]
    with open(out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=flds)
        w.writeheader()
        w.writerows(rows)
    temps = sorted({r["temperature_K"] for r in rows})
    print(f"  CED labels: {len(rows)} binder-temperature points  ->  {out_csv}")
    print(f"    temperatures present: {temps}")
    return rows


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    build_eintra(f"{OUT}/exampleB_eintra_references.csv")
    build_ced(f"{OUT}/exampleB_ced_labels.csv")
    print("done — now run: python scripts/make_exampleB_ced_figure.py")
