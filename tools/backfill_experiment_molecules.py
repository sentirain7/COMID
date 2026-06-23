#!/usr/bin/env python3
"""Backfill experiment_molecules for existing experiments.

Sources (priority):
1) Parse `packmol.inp` under `database/{exp_id}/...`
2) Infer from `asphalt_binder.yaml` using experiment metadata/exp_id

No synthetic fallback composition is injected when both sources fail.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml

from common.pathing import BINDER_ABBREV_REVERSE, parse_exp_id
from database.connection import session_scope
from database.models import ExperimentModel, MoleculeModel
from database.repositories.experiment_repo import ExperimentRepository

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASPHALT_BINDER_YAML = PROJECT_ROOT / "data" / "molecules" / "asphalt_binder.yaml"

_PACKMOL_UNDERSCORE_RE = re.compile(r"^([USL])_([A-Za-z]+)_([A-Za-z0-9]+)_(\d{4})$")
_PACKMOL_HYPHEN_RE = re.compile(r"^([USL])-([A-Za-z]+)-([A-Za-z0-9]+)-(\d{4})$")


def _load_asphalt_binder_config() -> dict[str, Any]:
    if not ASPHALT_BINDER_YAML.exists():
        return {}
    with ASPHALT_BINDER_YAML.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _sara_code_to_name(code: str) -> str:
    mapping = {
        "SA": "saturate",
        "AR": "aromatic",
        "RE": "resin",
        "AS": "asphaltene",
    }
    return mapping.get(code.upper(), "additive")


def _normalize_packmol_stem_to_mol_id(stem: str) -> str:
    stem = str(stem).strip()
    if not stem:
        return ""
    m = _PACKMOL_UNDERSCORE_RE.match(stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"
    m = _PACKMOL_HYPHEN_RE.match(stem)
    if m:
        return stem
    return stem.replace("__", "_")


def _parse_packmol_counts(packmol_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    current_mol_id: str | None = None
    for raw in packmol_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith("structure "):
            structure_path = Path(line.split(maxsplit=1)[1].strip())
            current_mol_id = _normalize_packmol_stem_to_mol_id(structure_path.stem)
            continue
        if line.lower().startswith("number ") and current_mol_id:
            try:
                count = int(float(line.split()[1]))
            except (IndexError, ValueError):
                current_mol_id = None
                continue
            if count > 0:
                counts[current_mol_id] = counts.get(current_mol_id, 0) + count
            current_mol_id = None
    return counts


def _find_packmol_file(exp_id: str) -> Path | None:
    exp_dir = PROJECT_ROOT / "database" / exp_id
    if not exp_dir.exists():
        return None
    candidates = [*exp_dir.glob("packmol.inp"), *exp_dir.glob("seed_*/packmol.inp")]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _infer_binder_counts_from_metadata(
    exp: ExperimentModel,
    config: dict[str, Any],
) -> dict[str, int]:
    meta = dict(exp.metadata_json or {})
    parsed = parse_exp_id(str(exp.exp_id or ""))
    binder_type = str(meta.get("binder_type") or "").strip()
    if not binder_type:
        binder_abbrev = str(parsed.get("binder_type") or "")
        binder_type = BINDER_ABBREV_REVERSE.get(binder_abbrev, binder_abbrev)

    structure_size = str(meta.get("structure_size") or parsed.get("structure_size") or "X1")
    aging_state = str(meta.get("aging_state") or parsed.get("aging_state") or "non_aging")
    temperature_k = meta.get("temperature_k") or parsed.get("temperature_k")
    try:
        temp_code = f"{int(round(float(temperature_k))):04d}"
    except (TypeError, ValueError):
        temp_code = "0293"

    binder_types = config.get("binder_types", {})
    if binder_type not in binder_types:
        return {}

    idx_map = {"X1": 0, "X2": 1, "X3": 2}
    size_idx = idx_map.get(structure_size, 0)

    aging_categories = config.get("aging_categories", {})
    primary_aging = aging_categories.get(aging_state, {})
    primary_prefix = str(primary_aging.get("prefix") or "U")
    fallback_aging = str(primary_aging.get("fallback_to") or "").strip()
    fallback_prefix = str(aging_categories.get(fallback_aging, {}).get("prefix") or "U")

    mol_defs = {
        str(item.get("base_id")): dict(item)
        for item in config.get("molecules", [])
        if isinstance(item, dict) and item.get("base_id")
    }

    result: dict[str, int] = {}
    composition = binder_types[binder_type].get("composition", {})
    for base_id, size_counts in composition.items():
        if not isinstance(size_counts, list) or len(size_counts) < 3:
            continue
        try:
            count = int(size_counts[size_idx])
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        mol_def = mol_defs.get(str(base_id), {})
        available = set(mol_def.get("available_aging") or [])
        use_prefix = primary_prefix if aging_state in available or not available else fallback_prefix
        mol_id = f"{use_prefix}-{base_id}-{temp_code}"
        result[mol_id] = count
    return result


def _lookup_binder_molecule_metadata(config: dict[str, Any], mol_id: str) -> dict[str, Any]:
    parts = mol_id.split("-")
    if len(parts) < 4:
        return {}
    base_id = "-".join(parts[1:-1])
    for item in config.get("molecules", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("base_id")) != base_id:
            continue
        sara = str(item.get("sara") or _sara_code_to_name(parts[1]))
        return {
            "name": item.get("name") or base_id,
            "molecular_weight": item.get("molecular_weight"),
            "num_atoms": item.get("atom_count"),
            "sara_type": sara,
            "base_id": base_id,
        }
    return {}


def _ensure_molecule_row(session, config: dict[str, Any], mol_id: str) -> None:
    row = session.query(MoleculeModel).filter(MoleculeModel.mol_id == mol_id).first()
    if row is not None:
        return

    meta = _lookup_binder_molecule_metadata(config, mol_id)
    sara_type = str(meta.get("sara_type") or _sara_code_to_name(mol_id.split("-")[1] if "-" in mol_id else ""))
    row = MoleculeModel(
        mol_id=mol_id,
        smiles=f"[{mol_id}]",
        name=str(meta.get("name") or mol_id),
        sara_type=sara_type,
        molecular_weight=meta.get("molecular_weight"),
        num_atoms=meta.get("num_atoms"),
        metadata_json={
            "autocreated": True,
            "source": "backfill_experiment_molecules",
            "base_id": meta.get("base_id"),
        },
    )
    session.add(row)
    session.flush()


def run(overwrite: bool) -> int:
    config = _load_asphalt_binder_config()
    created = 0
    updated = 0
    skipped_existing = 0
    unresolved: list[str] = []

    with session_scope() as session:
        repo = ExperimentRepository(session)
        experiments = (
            session.query(ExperimentModel).order_by(ExperimentModel.id.asc()).all()
        )
        for exp in experiments:
            exp_id = str(exp.exp_id or "")
            if not exp_id:
                continue

            existing_rows = repo.get_experiment_molecules(exp_id)
            if existing_rows and not overwrite:
                skipped_existing += 1
                continue

            counts: dict[str, int] = {}
            packmol = _find_packmol_file(exp_id)
            if packmol is not None:
                counts = _parse_packmol_counts(packmol)
            if not counts:
                counts = _infer_binder_counts_from_metadata(exp, config)

            if not counts:
                unresolved.append(exp_id)
                continue

            for mol_id in counts:
                _ensure_molecule_row(session, config, mol_id)

            row_count = repo.upsert_experiment_molecules(exp_id, counts)
            if row_count > 0:
                if existing_rows:
                    updated += 1
                else:
                    created += 1

    print(f"experiments_backfilled_created={created}")
    print(f"experiments_backfilled_updated={updated}")
    print(f"experiments_skipped_existing={skipped_existing}")
    print(f"experiments_unresolved={len(unresolved)}")
    if unresolved:
        print("unresolved_exp_ids=" + ",".join(unresolved))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill experiment_molecules table")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Rebuild experiment_molecules even when rows already exist",
    )
    args = parser.parse_args()
    return run(overwrite=args.overwrite)


if __name__ == "__main__":
    raise SystemExit(main())
