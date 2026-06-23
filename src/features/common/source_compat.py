"""Source type compatibility for amorphous_cell → interface_molecule_cell migration.

Provides constants and normalizers so that callers can accept both the legacy
``"amorphous_cell"`` source type string and the canonical
``"interface_molecule_cell"`` without scattering ad-hoc string comparisons
throughout the codebase.
"""

from __future__ import annotations

from contracts.schemas import LayerSourceType

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INTERFACE_LAYER_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "amorphous_cell",
        "interface_molecule_cell",
    }
)
"""Both the legacy and canonical source type strings for interface molecule layers."""

CANONICAL_INTERFACE_TYPE: str = LayerSourceType.INTERFACE_MOLECULE_CELL.value
"""The single canonical source type value for new records."""


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------


def normalize_source_type(raw: str) -> str:
    """Normalize legacy ``'amorphous_cell'`` to canonical ``'interface_molecule_cell'``.

    Args:
        raw: Source type string, possibly the legacy name.

    Returns:
        The canonical source type if *raw* was the legacy alias,
        otherwise *raw* unchanged.
    """
    if raw == "amorphous_cell":
        return CANONICAL_INTERFACE_TYPE
    return raw


def is_interface_like_source(source_type: str) -> bool:
    """Check if *source_type* represents an interface molecule layer.

    Accepts both the legacy ``"amorphous_cell"`` and the canonical
    ``"interface_molecule_cell"`` values.

    Args:
        source_type: Source type string to check.

    Returns:
        ``True`` if the value matches either the legacy or canonical name.
    """
    return source_type in INTERFACE_LAYER_SOURCE_TYPES
