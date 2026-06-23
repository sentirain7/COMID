"""Amorphous cell library application service."""

from __future__ import annotations

import math
import shutil
from datetime import UTC, datetime
from uuid import uuid4

from api.schemas import (
    AmorphousCellCreateRequest,
    AmorphousCellListResponse,
    AmorphousCellPreviewResponse,
    AmorphousCellResponse,
    MoleculeCountSpec,
    MoleculeExperimentRequest,
    StageDurationOverrideRequest,
    TypingChargePrecomputeRequest,
)
from api.utils.time_utils import iso_or_none as _iso
from common.hashing import compute_content_hash
from common.molecule_id import parse_molecule_id
from common.pathing import generate_amorphous_exp_id, get_amorphous_cell_path
from common.seed import generate_seed
from common.units import AVOGADRO
from contracts.errors import ContractError, DatabaseError, ErrorCode, SecurityError
from contracts.schemas import AmorphousBoundaryMode, RunTier, StudyType
from database.repositories.amorphous_repo import AmorphousCellRepository
from database.repositories.experiment_repo import ExperimentRepository
from features.common import run_in_session, run_in_session_commit
from features.common.density import (
    density_from_total_mass as _density_from_total_mass,
)
from features.common.density import (
    total_mass_from_types as _total_mass_from_types,
)
from features.common.workspace import (
    as_workspace_relative as _as_workspace_relative,
)
from features.common.workspace import (
    resolve_workspace_path as _resolve_workspace_path,
)
from features.experiments.submission import precompute_typing_charge, submit_molecule_experiment
from parsers.data_parser import DataParser


def _normalize_base_mol_id(raw_mol_id: str) -> str:
    try:
        parsed = parse_molecule_id(raw_mol_id.strip())
        return parsed.base_id
    except ValueError:
        return raw_mol_id.strip()


def _status_from_experiment_status(exp_status: str) -> str:
    mapping = {
        "pending": "queued",
        "queued": "queued",
        "building": "packing",
        "ready": "queued",
        "running": "running",
        "completed": "ready",
        "failed": "failed",
        "cancelled": "cancelled",
    }
    return mapping.get(exp_status, "queued")


def _to_response(row) -> AmorphousCellResponse:
    metadata = dict(row.metadata_json or {})
    components = list(row.components_json or [])
    component_mol_id = None
    if components:
        component_mol_id = str(components[0].get("mol_id", "")).strip() or None
    return AmorphousCellResponse(
        amorphous_id=row.amorphous_id,
        name=row.name,
        status=row.status,
        boundary_mode=row.boundary_mode,
        ff_type=row.ff_type,
        temperature_K=float(row.temperature_K or 298.0),
        atom_count=int(row.atom_count or 0),
        density=float(row.density) if row.density is not None else None,
        component_mol_id=component_mol_id,
        initial_density=float(row.target_density or 0.0),
        component_count=int(row.component_count or len(components)),
        components=components,
        lx_angstrom=float(row.lx_angstrom or 0.0),
        ly_angstrom=float(row.ly_angstrom or 0.0),
        lz_angstrom=float(row.lz_angstrom or 0.0),
        stabilization_exp_id=row.stabilization_exp_id,
        lammps_data_file_path=row.lammps_data_file_path,
        log_file_path=row.log_file_path,
        metadata=metadata,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def _build_source_hash(request: AmorphousCellCreateRequest, components: list[dict]) -> str:
    component_mol_id = str(components[0].get("mol_id", "")) if components else ""
    payload = {
        "component_mol_id": component_mol_id,
        "lx_angstrom": request.lx_angstrom,
        "ly_angstrom": request.ly_angstrom,
        "lz_angstrom": request.lz_angstrom,
        "initial_density": request.initial_density,
        "boundary_mode": request.boundary_mode.value,
        "ff_type": request.ff_type.value,
        "temperature_K": request.temperature_K,
        "minimize_steps": request.minimize_steps,
        "nvt_ps": request.nvt_ps,
        "npt_ps": request.npt_ps,
    }
    return compute_content_hash(payload)


def _compute_single_component_count(
    request: AmorphousCellCreateRequest,
    db,
    config,
) -> tuple[list[MoleculeCountSpec], list[dict]]:
    volume_a3 = request.lx_angstrom * request.ly_angstrom * request.lz_angstrom
    total_mass_g = request.initial_density * volume_a3 * 1e-24
    if total_mass_g <= 0:
        raise ContractError(
            ErrorCode.VALIDATION_ERROR,
            "Invalid amorphous target mass from initial density/box size",
            {
                "initial_density": request.initial_density,
                "box": [request.lx_angstrom, request.ly_angstrom, request.lz_angstrom],
            },
        )

    base_id = _normalize_base_mol_id(str(request.component_mol_id or ""))
    mw = float(db.get_molecule_molecular_weight(config, base_id, default=0.0) if config else 0.0)
    if mw <= 0:
        raise ContractError(
            ErrorCode.MOLECULE_NOT_FOUND,
            "Molecular weight not found for selected component. "
            "Register this non-binder molecule in single_moles.yaml first.",
            {"mol_id": base_id},
        )

    float_count = total_mass_g / mw * AVOGADRO
    count = max(1, int(math.floor(float_count + 0.5)))
    normalized_components = [
        {
            "mol_id": base_id,
            "weight_ratio": 100.0,
            "molecular_weight": mw,
            "estimated_count": count,
        }
    ]
    return [MoleculeCountSpec(mol_id=base_id, count=count)], normalized_components


def _build_stage_overrides(
    request: AmorphousCellCreateRequest,
) -> list[StageDurationOverrideRequest]:
    return [
        StageDurationOverrideRequest(
            stage_name="minimize",
            duration_steps=int(request.minimize_steps),
        ),
        StageDurationOverrideRequest(
            stage_name="nvt_equilibration",
            duration_ps=float(request.nvt_ps),
        ),
        StageDurationOverrideRequest(
            stage_name="npt_production",
            duration_ps=float(request.npt_ps),
        ),
    ]


def _sync_with_experiment(row, exp_repo: ExperimentRepository) -> None:
    if not row.stabilization_exp_id:
        return
    exp = exp_repo.get_by_id(row.stabilization_exp_id)
    if exp is None:
        return

    changed = False
    mapped_status = _status_from_experiment_status(str(exp.status))
    if row.status != mapped_status:
        row.status = mapped_status
        changed = True

    if exp.actual_atoms and int(exp.actual_atoms) != int(row.atom_count or 0):
        row.atom_count = int(exp.actual_atoms)
        changed = True

    if exp.data_file_path:
        try:
            data_path = _resolve_workspace_path(str(exp.data_file_path))
            final_path = data_path.parent / "final.data"
            chosen = final_path if final_path.exists() else data_path
            rel = _as_workspace_relative(chosen)
            if rel and row.lammps_data_file_path != rel:
                row.lammps_data_file_path = rel
                changed = True
        except SecurityError:
            pass

    if exp.log_file_path:
        try:
            log_rel = _as_workspace_relative(_resolve_workspace_path(str(exp.log_file_path)))
        except SecurityError:
            log_rel = None
        if log_rel and row.log_file_path != log_rel:
            row.log_file_path = log_rel
            changed = True

    if changed:
        row.updated_at = datetime.now(UTC)


async def create_amorphous_cell(
    request: AmorphousCellCreateRequest,
) -> AmorphousCellResponse:
    """Create and submit amorphous cell stabilization job."""
    from api.deps import get_aging_config, get_molecule_db

    db = get_molecule_db()
    config = get_aging_config()
    mol_counts, normalized_components = _compute_single_component_count(request, db, config)
    source_hash = _build_source_hash(request, normalized_components)

    def _get_existing(session):
        repo = AmorphousCellRepository(session)
        row = repo.get_by_source_hash(source_hash)
        if row is None:
            return None
        exp_repo = ExperimentRepository(session)
        _sync_with_experiment(row, exp_repo)
        return _to_response(row)

    existing = run_in_session(_get_existing)
    if existing is not None:
        return existing

    amorphous_id = f"amor_{uuid4().hex[:12]}"
    get_amorphous_cell_path(amorphous_id, create=True)

    def _create_draft(session):
        repo = AmorphousCellRepository(session)
        row = repo.create(
            amorphous_id=amorphous_id,
            name=request.name,
            status="assigning",
            source_hash=source_hash,
            components_json=normalized_components,
            component_count=len(normalized_components),
            lx_angstrom=request.lx_angstrom,
            ly_angstrom=request.ly_angstrom,
            lz_angstrom=request.lz_angstrom,
            target_density=request.initial_density,
            boundary_mode=request.boundary_mode.value,
            ff_type=request.ff_type.value,
            temperature_K=request.temperature_K,
            seed=request.seed,
            minimize_steps=request.minimize_steps,
            nvt_ps=request.nvt_ps,
            npt_ps=request.npt_ps,
            metadata_json={
                **(request.metadata or {}),
                "requested_components": normalized_components,
            },
        )
        return _to_response(row)

    run_in_session_commit(_create_draft)

    try:
        precompute_result = await precompute_typing_charge(
            TypingChargePrecomputeRequest(
                binder_type="custom",
                structure_size="X1",
                aging_state="non_aging",
                molecule_counts=mol_counts,
                additives=None,
                ff_type=request.ff_type.value,
            )
        )
        if precompute_result.failed > 0:
            failed_ids = [
                item.mol_id for item in precompute_result.details if item.status == "failed"
            ]
            raise ContractError(
                ErrorCode.TOPOLOGY_GENERATION_FAILED,
                "Typing/charge precompute failed for amorphous components",
                {"failed_molecules": failed_ids},
            )

        def _mark_packing(session):
            repo = AmorphousCellRepository(session)
            repo.update_status(
                amorphous_id,
                "packing",
                metadata_json={
                    **(request.metadata or {}),
                    "requested_components": normalized_components,
                    "typing_charge_cache": {
                        "cached": precompute_result.cached,
                        "computed": precompute_result.computed,
                    },
                },
            )

        run_in_session_commit(_mark_packing)

        study_type = (
            StudyType.BULK
            if request.boundary_mode == AmorphousBoundaryMode.PPP
            else StudyType.LAYER_BULKFF
        )

        # Generate amorphous-specific exp_id: {mol_id}_{boundary}_{temp}K_d{density}_{hash6}
        base_id = _normalize_base_mol_id(str(request.component_mol_id or ""))
        amor_exp_id = generate_amorphous_exp_id(
            mol_id=base_id,
            boundary_mode=request.boundary_mode.value,
            temperature_k=request.temperature_K,
            density=request.initial_density,
            seed=generate_seed(request.seed),
            ff_type=request.ff_type.value,
        )

        submitted = await submit_molecule_experiment(
            MoleculeExperimentRequest(
                binder_type="custom",
                structure_size="X1",
                aging_state="non_aging",
                molecule_counts=mol_counts,
                additives=None,
                temperature_K=request.temperature_K,
                run_tier=RunTier.SCREENING.value,
                ff_type=request.ff_type.value,
                box_dimensions=(request.lx_angstrom, request.ly_angstrom, request.lz_angstrom),
                study_type=study_type,
                seed=request.seed,
                stage_durations=_build_stage_overrides(request),
            ),
            exp_id_override=amor_exp_id,
        )

        def _mark_queued(session):
            repo = AmorphousCellRepository(session)
            row = repo.update_status(
                amorphous_id,
                "queued",
                stabilization_exp_id=submitted.exp_id,
                metadata_json={
                    **(request.metadata or {}),
                    "requested_components": normalized_components,
                    "submitted_job_id": submitted.job_id,
                    "study_type": study_type.value,
                },
            )
            if row is None:
                raise DatabaseError(
                    ErrorCode.RECORD_NOT_FOUND,
                    f"Amorphous cell not found during queue update: {amorphous_id}",
                )
            return _to_response(row)

        return run_in_session_commit(_mark_queued)
    except Exception as exc:
        error_message = str(exc)

        def _mark_failed(session):
            repo = AmorphousCellRepository(session)
            row = repo.get_by_id(amorphous_id)
            if row is None:
                return
            metadata = dict(row.metadata_json or {})
            metadata["last_error"] = error_message
            repo.update_status(
                amorphous_id,
                "failed",
                metadata_json=metadata,
            )

        run_in_session_commit(_mark_failed)
        raise


async def list_amorphous_cells(
    *,
    status: str | None = None,
    limit: int = 100,
    visibility: str = "library",
) -> AmorphousCellListResponse:
    """List amorphous cell templates."""
    bounded_limit = max(1, min(limit, 500))
    allowed_statuses = {"ready"} if visibility == "library" else None

    def _load(session):
        repo = AmorphousCellRepository(session)
        exp_repo = ExperimentRepository(session)
        rows = repo.list_recent(limit=bounded_limit * 3)
        for row in rows:
            _sync_with_experiment(row, exp_repo)
        if status:
            rows = [row for row in rows if str(row.status or "") == status]
        if allowed_statuses is not None:
            rows = [row for row in rows if str(row.status or "") in allowed_statuses]
        rows = rows[:bounded_limit]
        return AmorphousCellListResponse(
            total=len(rows),
            items=[_to_response(row) for row in rows],
        )

    return run_in_session(_load)


async def get_amorphous_cell(amorphous_id: str) -> AmorphousCellResponse:
    """Get amorphous cell detail."""

    def _load(session):
        repo = AmorphousCellRepository(session)
        exp_repo = ExperimentRepository(session)
        row = repo.get_by_id(amorphous_id)
        if row is None:
            raise DatabaseError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Amorphous cell not found: {amorphous_id}",
                {"amorphous_id": amorphous_id},
            )
        _sync_with_experiment(row, exp_repo)
        return _to_response(row)

    return run_in_session(_load)


async def get_amorphous_cell_preview(amorphous_id: str) -> AmorphousCellPreviewResponse:
    """Get amorphous cell preview payload for 3D rendering."""

    def _load(session):
        repo = AmorphousCellRepository(session)
        exp_repo = ExperimentRepository(session)
        row = repo.get_by_id(amorphous_id)
        if row is None:
            raise DatabaseError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Amorphous cell not found: {amorphous_id}",
                {"amorphous_id": amorphous_id},
            )
        _sync_with_experiment(row, exp_repo)
        if not row.lammps_data_file_path:
            raise ContractError(
                ErrorCode.STRUCTURE_NOT_FOUND,
                f"LAMMPS data path missing for amorphous cell: {amorphous_id}",
                {"amorphous_id": amorphous_id},
            )
        return {
            "amorphous_id": row.amorphous_id,
            "name": row.name,
            "boundary_mode": row.boundary_mode,
            "lammps_data_file_path": row.lammps_data_file_path,
        }

    row_data = run_in_session(_load)
    data_path = _resolve_workspace_path(str(row_data["lammps_data_file_path"]))
    if not data_path.exists():
        raise ContractError(
            ErrorCode.STRUCTURE_NOT_FOUND,
            f"Amorphous data file not found: {data_path}",
            {"amorphous_id": amorphous_id, "data_path": str(data_path)},
        )

    parser = DataParser()
    info = parser.parse(data_path)
    type_map = parser.estimate_elements_from_info(info)
    xyz_str, box_size = parser.info_to_xyz(
        info,
        type_map,
        comment=f"Amorphous preview {row_data['name']}",
    )

    atom_id_to_idx = {atom.atom_id: idx for idx, atom in enumerate(info.atoms)}
    bonds: list[list[int]] = []
    for bond in info.bonds:
        idx1 = atom_id_to_idx.get(bond.atom1_id)
        idx2 = atom_id_to_idx.get(bond.atom2_id)
        if idx1 is not None and idx2 is not None:
            bonds.append([idx1, idx2])

    total_mass_g_mol = _total_mass_from_types(
        atom_types=[atom.atom_type for atom in info.atoms],
        mass_by_type=info.masses,
    )
    density = _density_from_total_mass(total_mass_g_mol, box_size)

    return AmorphousCellPreviewResponse(
        amorphous_id=amorphous_id,
        xyz=xyz_str,
        box_size=box_size,
        n_atoms=info.n_atoms,
        n_bonds=len(bonds),
        bonds=bonds,
        density=density,
        boundary_mode=str(row_data["boundary_mode"]),
        type_map=type_map,
    )


async def delete_amorphous_cell(amorphous_id: str) -> dict:
    """Delete an amorphous cell and its artifacts."""

    def _delete(session):
        repo = AmorphousCellRepository(session)
        row = repo.get_by_id(amorphous_id)
        if row is None:
            raise DatabaseError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Amorphous cell not found: {amorphous_id}",
                {"amorphous_id": amorphous_id},
            )
        repo.delete(amorphous_id)
        return {"amorphous_id": amorphous_id, "name": row.name}

    deleted = run_in_session_commit(_delete)
    work_dir = get_amorphous_cell_path(amorphous_id)
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    return {"deleted": True, **deleted}


# ── Box size presets from completed binder experiments ──

_FALLBACK_PRESETS = [
    {"key": "X1", "label": "X1 (40×40×40 Å)", "lx": 40.0, "ly": 40.0, "lz": 40.0, "count": 0},
    {"key": "X2", "label": "X2 (50×50×50 Å)", "lx": 50.0, "ly": 50.0, "lz": 50.0, "count": 0},
    {"key": "X3", "label": "X3 (60×60×60 Å)", "lx": 60.0, "ly": 60.0, "lz": 60.0, "count": 0},
]

_VALID_SIZES = {"X1", "X2", "X3"}


def get_box_presets_from_db() -> list[dict]:
    """Return box size presets derived from completed binder experiments.

    Groups by structure_size (X1/X2/X3), computes median box dimensions,
    rounds to 1 Å. Falls back to hardcoded defaults when DB is empty.
    """
    from collections import defaultdict
    from statistics import median

    from common.pathing import parse_exp_id
    from contracts.schemas import AmorphousBoundaryMode
    from database.models.experiment import ExperimentModel

    _boundary_values = {m.value for m in AmorphousBoundaryMode}

    def _query(session):
        rows = (
            session.query(
                ExperimentModel.exp_id,
                ExperimentModel.box_lx,
                ExperimentModel.box_ly,
                ExperimentModel.box_lz,
            )
            .filter(
                ExperimentModel.status == "completed",
                ExperimentModel.box_lx.isnot(None),
                ExperimentModel.box_ly.isnot(None),
                ExperimentModel.box_lz.isnot(None),
            )
            .all()
        )
        groups: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
        for exp_id, lx, ly, lz in rows:
            parsed = parse_exp_id(str(exp_id))
            size = str(parsed.get("structure_size") or "")
            # Skip amorphous-format exp_ids (boundary modes like ppp/ppf)
            if size in _boundary_values or size not in _VALID_SIZES:
                continue
            groups[size].append((float(lx), float(ly), float(lz)))

        presets = []
        for size_key in ("X1", "X2", "X3"):
            dims = groups.get(size_key)
            if not dims:
                continue
            med_lx = round(median(d[0] for d in dims))
            med_ly = round(median(d[1] for d in dims))
            med_lz = round(median(d[2] for d in dims))
            label = f"X{size_key[1]} ({med_lx}×{med_ly}×{med_lz} Å)"
            presets.append(
                {
                    "key": size_key,
                    "label": label,
                    "lx": float(med_lx),
                    "ly": float(med_ly),
                    "lz": float(med_lz),
                    "count": len(dims),
                }
            )
        return presets

    result = run_in_session(_query)
    return result if result else list(_FALLBACK_PRESETS)
