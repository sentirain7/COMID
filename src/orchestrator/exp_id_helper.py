"""exp_id generation helper — material_id parsing + generate_exp_id delegation.

Fixes aging_state parsing bug: "AAA1_X1_short_aging".split("_")[2] returned
"short" instead of "short_aging". Now uses "_".join(parts[2:]) for correct
multi-word aging state extraction.
"""

from common.pathing import generate_exp_id


def parse_material_id(material_id: str) -> tuple[str, str, str]:
    """Parse material_id into (binder_type, structure_size, aging_state).

    Args:
        material_id: e.g. "AAA1_X1_non_aging", "AAK1_X3_short_aging", "custom"

    Returns:
        Tuple of (binder_type, structure_size, aging_state)
    """
    parts = material_id.split("_")
    binder_type = parts[0] if len(parts) > 0 else "custom"
    structure_size = parts[1] if len(parts) > 1 else "X1"
    # Bug fix: join remaining parts for multi-word aging states like "short_aging"
    aging_state = "_".join(parts[2:]) if len(parts) > 2 else "non_aging"
    return binder_type, structure_size, aging_state


def generate_exp_id_from_material(
    material_id: str,
    temperature_k: float,
    ff_type: str,
    atom_count: int,
    seed: int,
    additive: str | None = None,
) -> str:
    """Generate exp_id from material_id (SSOT delegation).

    Args:
        material_id: Material identifier (e.g. "AAA1_X1_non_aging")
        temperature_k: Temperature in Kelvin
        ff_type: Force field type value (e.g. "bulk_ff_gaff2")
        atom_count: Target atom count
        seed: Random seed
        additive: Optional additive name

    Returns:
        Generated experiment ID string
    """
    binder_type, structure_size, aging_state = parse_material_id(material_id)
    return generate_exp_id(
        binder_type=binder_type,
        structure_size=structure_size,
        temperature_k=temperature_k,
        additive=additive,
        ff_type=ff_type,
        aging_state=aging_state,
        atom_count=atom_count,
        seed=seed,
    )
