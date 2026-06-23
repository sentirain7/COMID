"""Ingest MDML (COMPASS III) pretrain labels into the structural feature store.

MDML already computed the 32 structural features per system and saved them in
``*_pt_summary.csv`` (node 30 + sys 2 columns + ``target_y`` label). We read
those directly — no need to re-parse 5k+ complex .mol files — and store them
with ``source=mdml_pretrain`` / ``force_field=compass_iii`` so the V7
challenger can mix them with our GAFF2 rows (density), filtered by FF tag.

CED note: MDML CED = NonBondEnergy/Volume (negative, different unit from our
MJ/m³). It is ingested under ``label_ced_compass`` so it never silently mixes
with our reconciled CED — density is the safe cross-FF target.

Usage:
  PYTHONPATH=src:packages python scripts/ingest_mdml_pretrain.py \
      --mdml-root /path/to/MDML/XGBoost_RandomForest_Analysis \
      --density-csv Density_20260612_LigninHoldOut \
      --ced-csv CED_20260612_LigninHoldOut
"""

import argparse
import re
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--mdml-root",
        default="/path/to/MDML/XGBoost_RandomForest_Analysis",
    )
    p.add_argument("--density-csv", default="Density_20260612_LigninHoldOut")
    p.add_argument("--ced-csv", default="CED_20260612_LigninHoldOut")
    p.add_argument("--store-path", default=None)
    return p.parse_args()


# Material token in MDML filenames (A1LACNT..., used as holdout group key).
_GROUP_RE = re.compile(r"(LIG|LIGNIN|SBS|LIME|CNT|GRP)", re.IGNORECASE)


def _group_key(mol_id: str) -> str:
    if not isinstance(mol_id, str):
        return "unknown"
    m = _GROUP_RE.search(mol_id)
    return m.group(1).upper() if m else "base"


def _find_summary(root: Path, tag: str) -> Path | None:
    direct = root / tag / f"{tag}_pt_summary.csv"
    if direct.exists():
        return direct
    hits = list(root.glob(f"{tag}/*pt_summary.csv"))
    return hits[0] if hits else None


def main() -> int:
    args = parse_args()
    import pandas as pd

    from ml.structural_feature_store import (
        FF_COMPASS,
        SOURCE_MDML,
        StructuralFeatureStore,
    )
    from ml.structural_features import STRUCTURAL_FEATURE_NAMES

    root = Path(args.mdml_root)
    store = StructuralFeatureStore(
        Path(args.store_path) if args.store_path else None
    )

    targets = [("density", args.density_csv), ("ced_compass", args.ced_csv)]
    # Build rows keyed by mol_id so density + CED labels merge per system.
    rows_by_key: dict[str, dict] = {}
    feature_names = list(STRUCTURAL_FEATURE_NAMES)

    for label_name, tag in targets:
        csv = _find_summary(root, tag)
        if csv is None:
            print(f"[skip] no pt_summary for {tag}")
            continue
        df = pd.read_csv(csv)
        missing = [c for c in feature_names if c not in df.columns]
        if missing:
            print(f"[skip] {tag}: missing feature cols {missing[:3]}...")
            continue
        n = 0
        for _, r in df.iterrows():
            if pd.isna(r.get("target_y")):
                continue
            mol_id = str(r.get("mol_id", r.get("filename", n)))
            key = f"mdml::{mol_id}"
            entry = rows_by_key.setdefault(
                key,
                {
                    "features": {c: float(r[c]) for c in feature_names},
                    "labels": {},
                    "group_key": _group_key(mol_id),
                    "row_key": key,
                },
            )
            entry["labels"][label_name] = float(r["target_y"])
            n += 1
        print(f"[ok] {label_name}: {n} rows from {csv.name}")

    rows = [
        StructuralFeatureStore.make_row(
            features=e["features"],
            labels=e["labels"],
            source=SOURCE_MDML,
            force_field=FF_COMPASS,
            group_key=e["group_key"],
            row_key=e["row_key"],
        )
        for e in rows_by_key.values()
    ]
    written = store.upsert(rows, source=SOURCE_MDML)
    print(f"\n[store] upserted {written} MDML rows")
    print("[summary]", store.summary().get("sources", {}).get(SOURCE_MDML))
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
