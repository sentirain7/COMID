"""Protocol hash generation — delegates raw hashing to common/hashing SSOT.

Generates deterministic hashes that uniquely identify
simulation protocols for provenance tracking.
"""

from typing import Any

from common.hashing import compute_content_hash
from common.logging import get_logger

logger = get_logger("protocols.protocol_hash")


class ProtocolHasher:
    """Generates hashes for protocol configurations.

    Hashes are deterministic and can be used to verify
    that two simulations used identical protocols.

    Uses compute_content_hash() from common/hashing as SSOT
    for the underlying hash computation.
    """

    def __init__(self, hash_length: int = 8):
        """Initialize hasher.

        Args:
            hash_length: Length of output hash string
        """
        self.hash_length = hash_length

    def hash(
        self,
        tier: str,
        force_field: str,
        ff_version: str,
        topology_hash: str,
        temperature_K: float,
        pressure_atm: float,
        step_names: list[str],
        extra_params: dict[str, Any] | None = None,
    ) -> str:
        """Generate protocol hash.

        Args:
            tier: Tier type (screening, confirm, etc.)
            force_field: Force field name
            ff_version: Force field version
            topology_hash: Topology hash from structure
            temperature_K: Temperature in Kelvin
            pressure_atm: Pressure in atmospheres
            step_names: List of protocol step names
            extra_params: Additional parameters affecting protocol

        Returns:
            Short hash string (e.g., "a1b2c3d4")
        """
        data = {
            "tier": tier,
            "force_field": force_field,
            "ff_version": ff_version,
            "topology_hash": topology_hash,
            "temperature_K": round(temperature_K, 2),
            "pressure_atm": round(pressure_atm, 4),
            "step_names": sorted(step_names),
        }

        if extra_params:
            data["extra"] = self._normalize_dict(extra_params)

        return compute_content_hash(data, length=self.hash_length)

    def _normalize_dict(self, d: dict) -> dict:
        """Normalize dictionary for consistent hashing."""
        result = {}
        for key in sorted(d.keys()):
            value = d[key]
            if isinstance(value, dict):
                result[key] = self._normalize_dict(value)
            elif isinstance(value, list | tuple):
                result[key] = sorted(str(v) for v in value)  # type: ignore[assignment]
            elif isinstance(value, float):
                result[key] = round(value, 6)  # type: ignore[arg-type]
            else:
                result[key] = value
        return result
