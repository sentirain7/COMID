"""
LAMMPS restart script generator.

Standalone functions extracted from LAMMPSInputGenerator for generating
checkpoint-restart LAMMPS input scripts.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from common.logging import get_logger
from protocols.lammps_force_field import (
    generate_force_field,
    generate_group_energy_commands,
    generate_layer_pe_commands,
    generate_neighbor_settings,
    generate_package_commands,
    generate_pair_coeffs,
)

if TYPE_CHECKING:
    from contracts.schemas import GroupEnergySpec
    from protocols.protocol_chain import ProtocolChain

logger = get_logger("protocols.lammps_restart")


def generate_restart_script_body(
    chain: ProtocolChain,
    restart_file: Path,
    remaining_indices: list[int],
    *,
    group_energy_spec: GroupEnergySpec | None = None,
    opt_profile: dict | None = None,
    coeffs_in_data: bool = True,
    has_charges: bool = True,
    has_bonds: bool = True,
    crystal_type_ids: set[int] | None = None,
    generate_header_fn: Callable[..., str] | None = None,
    generate_step_fn: Callable[..., str] | None = None,
) -> str:
    """Build the LAMMPS script text for a checkpoint restart.

    Args:
        chain: Full protocol chain.
        restart_file: Path to the restart file.
        remaining_indices: Original 0-based indices of stages still to execute.
        group_energy_spec: Optional group energy specification.
        opt_profile: Optimization profile dict (from LAMMPS caps probe).
        coeffs_in_data: Whether pair coefficients are in the data file.
        has_charges: Whether the system has partial charges.
        has_bonds: Whether the system has bonded interactions.
        crystal_type_ids: Set of crystal atom type IDs.
        generate_header_fn: Callable(chain) -> str for header generation.
        generate_step_fn: Callable(step, chain, i, gg_columns) -> str for step generation.

    Returns:
        Complete LAMMPS restart script as a string.
    """
    sections: list[str] = []

    assert generate_header_fn is not None, "generate_header_fn is required"
    assert generate_step_fn is not None, "generate_step_fn is required"

    # 1. Header (units, atom_style, boundary, etc.)
    sections.append(generate_header_fn(chain))

    # 2. Force field styles (pair_style, bond_style -- NOT stored in restart)
    sections.append(generate_force_field(chain, has_charges=has_charges, has_bonds=has_bonds))

    # 3. Package commands (KOKKOS -- must precede box definition)
    pkg = generate_package_commands(opt_profile)
    if pkg:
        sections.append(pkg)

    # 4. read_restart (replaces read_data)
    sections.append("# Resume from checkpoint")
    sections.append(f"read_restart {restart_file}")
    sections.append("")

    # 5. Pair coefficients
    sections.append(generate_pair_coeffs(chain, coeffs_in_data=coeffs_in_data))

    # 6. Neighbor settings
    sections.append(generate_neighbor_settings(opt_profile))

    # 7. Group energy decomposition (groups are restored by restart,
    #    but computes/fixes must be re-declared).
    gg_columns: list[str] = []
    if group_energy_spec and (group_energy_spec.groups or group_energy_spec.group_selectors):
        sections.append("")
        sections.append(generate_group_energy_commands(group_energy_spec))
        gg_columns = [f"c_gg_{p.label}" for p in group_energy_spec.pairs]
        if chain.study_type.value == "layer_bulkff" and group_energy_spec.layer_count:
            layer_pe_cmds = generate_layer_pe_commands(group_energy_spec)
            if layer_pe_cmds:
                sections.append("")
                sections.append(layer_pe_cmds)
                gg_columns.extend(
                    [f"c_pe_layer_{idx}" for idx in range(int(group_energy_spec.layer_count))]
                )

    # 8. Only remaining stages -- keep original indices for @@STAGE
    for i in remaining_indices:
        if i >= len(chain.steps):
            continue
        step = chain.steps[i]
        sections.append("")
        sections.append(f"# Step {i + 1}: {step.name} (resumed)")
        sections.append(f'print "@@STAGE {i} {step.name}"')
        sections.append(generate_step_fn(step, chain, i, gg_columns=gg_columns))

    # 9. Final state
    sections.append("")
    sections.append("# Write final state")
    sections.append("write_data final.data")
    sections.append("write_restart final.restart")

    return "\n".join(sections)
