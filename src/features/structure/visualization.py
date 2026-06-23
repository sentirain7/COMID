"""Structure visualization operations."""

import json
from pathlib import Path

from common.logging import get_logger
from contracts.errors import (
    ContractError,
    DatabaseError,
    ErrorCode,
    ParserError,
    SecurityError,
)
from features.common import run_in_session
from features.common.density import (
    density_from_total_mass as _density_from_total_mass,
)
from features.common.density import (
    total_mass_from_types as _total_mass_from_types,
)

logger = get_logger("features.structure.visualization")


def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        logger.warning(f"Failed to load JSON from {path}: {exc}")
        return None


def _save_json(path: Path, payload: dict | list) -> None:
    try:
        path.write_text(json.dumps(payload))
    except Exception as exc:
        logger.warning(f"Failed to write JSON to {path}: {exc}")


def _load_or_build_bond_cache(
    data_file: Path,
    bond_cache_path: Path,
    data_parser,
) -> tuple[list[list[int]], dict[str, str] | None, float]:
    source_mtime_ns = data_file.stat().st_mtime_ns
    cached = _load_json(bond_cache_path)

    if isinstance(cached, dict):
        cache_mtime = cached.get("source_mtime_ns")
        atom_id_pairs = cached.get("atom_id_pairs")
        cached_type_map = cached.get("type_map")
        cached_total_mass = cached.get("total_mass_g_mol")
        if (
            cache_mtime == source_mtime_ns
            and isinstance(atom_id_pairs, list)
            and all(isinstance(pair, list) and len(pair) == 2 for pair in atom_id_pairs)
            and isinstance(cached_total_mass, int | float)
        ):
            return (
                atom_id_pairs,
                cached_type_map if isinstance(cached_type_map, dict) else None,
                float(cached_total_mass),
            )

    info = data_parser.parse(data_file)
    atom_id_pairs = [[bond.atom1_id, bond.atom2_id] for bond in info.bonds]
    inferred_type_map = data_parser.estimate_elements_from_info(info)
    total_mass_g_mol = _total_mass_from_types(
        atom_types=[atom.atom_type for atom in info.atoms],
        mass_by_type=info.masses,
    )
    _save_json(
        bond_cache_path,
        {
            "version": 1,
            "source_mtime_ns": source_mtime_ns,
            "atom_id_pairs": atom_id_pairs,
            "type_map": inferred_type_map,
            "total_mass_g_mol": total_mass_g_mol,
        },
    )
    return atom_id_pairs, inferred_type_map, total_mass_g_mol


async def get_structure_xyz(exp_id: str, stage: str) -> dict:
    from api.utils.structure_path import get_experiment_dir, get_final_stage, get_structure_path
    from contracts.schemas import StructureStage
    from database.repositories.experiment_repo import ExperimentRepository
    from parsers.data_parser import DataParser
    from parsers.dump_parser import DumpParser

    valid_stages = [s.value for s in StructureStage]
    if stage not in valid_stages:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Invalid stage. Must be one of: {valid_stages}",
            {"stage": stage, "valid_stages": valid_stages},
        )

    try:

        def _load(session):
            repo = ExperimentRepository(session)
            experiment = repo.get_by_id(exp_id)
            if not experiment:
                raise DatabaseError(
                    ErrorCode.RECORD_NOT_FOUND,
                    f"Experiment {exp_id} not found",
                    {"exp_id": exp_id},
                )

            exp_dir = get_experiment_dir(experiment.lammps_working_dir, experiment.data_file_path)
            if not exp_dir:
                raise SecurityError(
                    ErrorCode.STRUCTURE_NOT_FOUND,
                    "Experiment directory not found",
                    {"exp_id": exp_id},
                )

            tier = experiment.run_tier or "screening"
            ff_type = experiment.ff_type
            return exp_dir, tier, ff_type

        exp_dir, tier, ff_type = run_in_session(_load)
    except ContractError:
        raise
    except Exception as exc:
        logger.error(f"Database error for {exp_id}: {exc}")
        raise DatabaseError(
            ErrorCode.DATABASE_ERROR,
            "Database error",
            {"exp_id": exp_id},
        ) from exc

    actual_stage = get_final_stage(exp_dir, tier) if stage == "final" else stage
    structure_path = get_structure_path(exp_dir, actual_stage)

    if not structure_path.exists():
        raise SecurityError(
            ErrorCode.STRUCTURE_NOT_FOUND,
            f"Structure not found for stage '{stage}'",
            {"exp_id": exp_id, "stage": stage},
        )

    type_map_path = exp_dir / "type_map.json"
    type_map_raw = _load_json(type_map_path)
    type_map = type_map_raw if isinstance(type_map_raw, dict) else None

    bonds: list[list[int]] = []
    data_file = exp_dir / "data.lammps"
    bond_cache_path = exp_dir / "bond_cache.json"
    is_reactive_ff = ff_type == "reaxff"
    if is_reactive_ff:
        logger.warning(f"Bond visualization disabled for ReaxFF experiment {exp_id}")
    density: float | None = None
    box_size: tuple[float, float, float] | None = None

    try:
        if actual_stage == "initial":
            parser = DataParser()
            info = parser.parse(structure_path)

            if not is_reactive_ff:
                atom_id_to_idx = {atom.atom_id: idx for idx, atom in enumerate(info.atoms)}
                for bond in info.bonds:
                    idx1 = atom_id_to_idx.get(bond.atom1_id)
                    idx2 = atom_id_to_idx.get(bond.atom2_id)
                    if idx1 is not None and idx2 is not None:
                        bonds.append([idx1, idx2])

            if type_map is None:
                type_map = parser.estimate_elements_from_info(info)
                _save_json(type_map_path, type_map)

            xyz_str, box_size = parser.info_to_xyz(
                info, type_map, comment="Initial structure (t=0)"
            )
            total_mass_g_mol = _total_mass_from_types(
                atom_types=[atom.atom_type for atom in info.atoms],
                mass_by_type=info.masses,
            )
            density = _density_from_total_mass(total_mass_g_mol, box_size)
            timestep = 0
        else:
            dump_parser = DumpParser()
            frame = dump_parser.parse_last_frame(structure_path)

            if not frame:
                raise ParserError(
                    ErrorCode.DUMP_PARSE_FAILED,
                    "Failed to parse dump file",
                    file_path=str(structure_path),
                )

            if "id" not in frame.columns:
                logger.warning(
                    f"Dump file lacks 'id' column, bonds disabled for {exp_id}/{actual_stage}"
                )
            elif not is_reactive_ff and data_file.exists():
                atom_id_to_idx = {atom["id"]: idx for idx, atom in enumerate(frame.atoms)}
                data_parser = DataParser()
                atom_id_pairs, cached_type_map, total_mass_g_mol = _load_or_build_bond_cache(
                    data_file,
                    bond_cache_path,
                    data_parser,
                )

                if type_map is None:
                    type_map = cached_type_map or {}
                    if type_map:
                        _save_json(type_map_path, type_map)

                skipped = 0
                for atom1_id, atom2_id in atom_id_pairs:
                    idx1 = atom_id_to_idx.get(atom1_id)
                    idx2 = atom_id_to_idx.get(atom2_id)
                    if idx1 is not None and idx2 is not None:
                        bonds.append([idx1, idx2])
                    else:
                        skipped += 1
                if skipped > 0:
                    logger.warning(
                        f"Skipped {skipped}/{len(atom_id_pairs)} bonds due to missing atom IDs"
                    )
                box_size = dump_parser.get_box_dimensions(frame)
                density = _density_from_total_mass(total_mass_g_mol, box_size)
            elif type_map is None and data_file.exists():
                data_parser = DataParser()
                _atom_id_pairs, cached_type_map, total_mass_g_mol = _load_or_build_bond_cache(
                    data_file,
                    bond_cache_path,
                    data_parser,
                )
                type_map = cached_type_map or {}
                if type_map:
                    _save_json(type_map_path, type_map)
                box_size = dump_parser.get_box_dimensions(frame)
                density = _density_from_total_mass(total_mass_g_mol, box_size)

            if bonds:
                dump_parser.make_molecules_whole(frame, bonds)
            xyz_str = dump_parser.frame_to_xyz(frame, type_map or {})
            if box_size is None:
                box_size = dump_parser.get_box_dimensions(frame)
            if density is None and data_file.exists():
                data_parser = DataParser()
                _atom_id_pairs, _cached_type_map, total_mass_g_mol = _load_or_build_bond_cache(
                    data_file,
                    bond_cache_path,
                    data_parser,
                )
                density = _density_from_total_mass(total_mass_g_mol, box_size)
            timestep = frame.timestep
            info = type("info", (), {"n_atoms": frame.n_atoms})()

    except ContractError:
        raise
    except Exception as exc:
        logger.error(f"Failed to parse structure for {exp_id}/{stage}: {exc}")
        raise ParserError(
            ErrorCode.PARSER_ERROR,
            "Structure parsing failed",
            details={"exp_id": exp_id, "stage": stage},
        ) from exc

    return {
        "xyz": xyz_str,
        "box_size": box_size,
        "n_atoms": info.n_atoms,
        "n_bonds": len(bonds),
        "bonds": bonds,
        "density": density,
        "stage": actual_stage,
        "timestep": timestep,
    }
