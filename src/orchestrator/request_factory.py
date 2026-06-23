"""Factory functions for BuildRequest / ProtocolRequest creation.

Consolidates 7+ manual construction sites into two reusable helpers.
target_atoms defaults are derived from DEFAULT_TIER_POLICY (SSOT).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.seed import generate_seed
from config.dashboard_settings import resolve_submission_e_intra_method
from contracts.policies.tier import DEFAULT_TIER_POLICY
from contracts.schemas import (
    BuildRequest,
    EquilibrationSettings,
    FFType,
    ProtocolRequest,
    RunTier,
    StudyType,
)

if TYPE_CHECKING:
    from contracts.schemas import LayerSpec, TensileSpec


def create_build_request(
    composition: dict[str, float],
    seed: int | None = None,
    target_atoms: int | None = None,
    tier: str | RunTier = RunTier.SCREENING,
    composition_mode: str = "wt_percent",
    box_dimensions: tuple[float, float, float] | None = None,
    prebuilt_data_file_path: str | None = None,
    initial_density: float | None = None,
) -> BuildRequest:
    """Create a BuildRequest with tier-appropriate defaults.

    Args:
        composition: SARA wt% dict or mol_id → count dict
        seed: Random seed
        target_atoms: Override target atoms (None = derive from tier policy)
        tier: Run tier for default target_atoms lookup
        composition_mode: "wt_percent" (default) or "mol_count"
        box_dimensions: Optional explicit orthorhombic box dimensions (lx, ly, lz)
        prebuilt_data_file_path: Optional prebuilt LAMMPS data path (skip structure build)
        initial_density: Optional initial packing density (g/cm3) for Packmol

    Returns:
        BuildRequest instance
    """
    if target_atoms is None:
        tier_value = tier.value if isinstance(tier, RunTier) else tier
        target_atoms = DEFAULT_TIER_POLICY.get_target_atoms(tier_value)

    kwargs: dict = {
        "composition": composition,
        "target_atoms": target_atoms,
        "seed": generate_seed(seed),
        # 항상 명시: BuildRequest 스키마 기본값은 "mol_count"라서 wt_percent를
        # 생략하면 SARA wt% dict가 분자 수로 해석돼 빌드가 E2002로 실패한다
        # (이 팩토리의 계약은 "wt_percent가 기본" — 실 E2E에서 발견된 latent 버그).
        "composition_mode": composition_mode,
    }
    if box_dimensions is not None:
        kwargs["box_dimensions"] = box_dimensions
    if prebuilt_data_file_path:
        kwargs["prebuilt_data_file_path"] = prebuilt_data_file_path
    if initial_density is not None:
        kwargs["initial_density"] = initial_density

    return BuildRequest(**kwargs)


def create_protocol_request(
    tier: str | RunTier = RunTier.SCREENING,
    ff_type: str | FFType = FFType.BULK_FF_GAFF2,
    study_type: str | StudyType = StudyType.BULK,
    temperature_K: float = 298.0,
    pressure_atm: float = 1.0,
    data_file_path: str = "",
    e_intra_method: str | None = None,
    ced_provenance_mol_counts: dict[str, int] | None = None,
    ced_provenance_mol_counts_by_layer: dict[str, dict[str, int]] | None = None,
    ced_provenance_layer_volumes_A3: dict[str, float] | None = None,
    ced_provenance_layer_labels: list[str] | None = None,
    tensile_spec: TensileSpec | None = None,
    layer_spec: LayerSpec | None = None,
    equilibration_settings: dict | EquilibrationSettings | None = None,
    skip_stage_keys: list[str] | None = None,
) -> ProtocolRequest:
    """Create a ProtocolRequest.

    Args:
        tier: Run tier
        ff_type: Force field type
        study_type: Study type (bulk/layer)
        temperature_K: Temperature in Kelvin
        pressure_atm: Pressure in atm
        data_file_path: Path to data file (empty = set by pipeline)
        e_intra_method: Optional explicit method override. When omitted,
            submission defaults resolve from settings.json, then env, then
            single_molecule_vacuum.
        tensile_spec: Optional tensile test specification
        layer_spec: Optional layer specification (for grip z-boundary)
        equilibration_settings: Optional high-temperature/high-pressure equilibration settings

    Returns:
        ProtocolRequest instance
    """
    run_tier = RunTier(tier) if isinstance(tier, str) else tier
    if isinstance(ff_type, str):
        try:
            ff = FFType(ff_type)
        except ValueError:
            raise ValueError(
                f"Stale ff_type='{ff_type}'. Run scripts/migrate_bulk_ff_to_gaff2.py --verify"
            ) from None
    else:
        ff = ff_type
    st = StudyType(study_type) if isinstance(study_type, str) else study_type
    resolved_e_intra_method = resolve_submission_e_intra_method(e_intra_method).value

    # Convert equilibration_settings dict to EquilibrationSettings if needed
    eq_settings: EquilibrationSettings | None = None
    if equilibration_settings is not None:
        if isinstance(equilibration_settings, dict):
            eq_settings = EquilibrationSettings(**equilibration_settings)
        else:
            eq_settings = equilibration_settings

    kwargs: dict = {
        "run_tier": run_tier,
        "ff_type": ff,
        "study_type": st,
        "temperature_K": temperature_K,
        "pressure_atm": pressure_atm,
        "data_file_path": data_file_path,
        "e_intra_method": resolved_e_intra_method,
    }
    if ced_provenance_mol_counts:
        kwargs["ced_provenance_mol_counts"] = {
            str(mol_id): int(count)
            for mol_id, count in ced_provenance_mol_counts.items()
            if str(mol_id).strip() and int(count) > 0
        }
    if ced_provenance_mol_counts_by_layer:
        layer_counts: dict[str, dict[str, int]] = {}
        for layer_label, mol_counts in ced_provenance_mol_counts_by_layer.items():
            clean_counts = {
                str(mol_id): int(count)
                for mol_id, count in (mol_counts or {}).items()
                if str(mol_id).strip() and int(count) > 0
            }
            if clean_counts:
                layer_counts[str(layer_label)] = clean_counts
        if layer_counts:
            kwargs["ced_provenance_mol_counts_by_layer"] = layer_counts
    if ced_provenance_layer_volumes_A3:
        layer_volumes = {
            str(layer_label): float(volume)
            for layer_label, volume in ced_provenance_layer_volumes_A3.items()
            if str(layer_label).strip() and float(volume) > 0.0
        }
        if layer_volumes:
            kwargs["ced_provenance_layer_volumes_A3"] = layer_volumes
    if ced_provenance_layer_labels:
        layer_labels = [str(label) for label in ced_provenance_layer_labels if str(label).strip()]
        if layer_labels:
            kwargs["ced_provenance_layer_labels"] = layer_labels
    if tensile_spec is not None:
        kwargs["tensile_spec"] = tensile_spec
    if layer_spec is not None:
        kwargs["layer_spec"] = layer_spec
    if eq_settings is not None:
        kwargs["equilibration_settings"] = eq_settings
    if skip_stage_keys:
        kwargs["skip_stage_keys"] = skip_stage_keys

    return ProtocolRequest(**kwargs)
