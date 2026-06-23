"""
Hashing utilities - SSOT for hash generation.

All sessions must use these functions for hash computation.
"""

import hashlib
import json
from pathlib import Path


def compute_file_hash(file_path: str | Path, algorithm: str = "sha256") -> str:
    """
    Compute hash of a file.

    Args:
        file_path: Path to file
        algorithm: Hash algorithm (sha256, md5, sha1)

    Returns:
        Hex string of hash
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    hasher = hashlib.new(algorithm)

    with open(path, "rb") as f:
        # Read in chunks for large files
        while chunk := f.read(8192):
            hasher.update(chunk)

    return hasher.hexdigest()


def compute_content_hash(
    content: str | bytes | dict | list, algorithm: str = "sha256", length: int = 0
) -> str:
    """
    Compute hash of content.

    Args:
        content: Content to hash (str, bytes, dict, or list)
        algorithm: Hash algorithm
        length: Truncate to this length (0 = full)

    Returns:
        Hex string of hash
    """
    hasher = hashlib.new(algorithm)

    if isinstance(content, dict) or isinstance(content, list):
        # Serialize JSON deterministically
        content = json.dumps(content, sort_keys=True, default=str)

    if isinstance(content, str):
        content = content.encode("utf-8")

    hasher.update(content)
    result = hasher.hexdigest()

    if length > 0:
        return result[:length]
    return result


def compute_topology_hash(
    mol_ids: list[str], mol_counts: dict[str, int], ff_name: str, ff_version: str
) -> str:
    """
    Compute topology hash for reproducibility.

    Args:
        mol_ids: List of molecule IDs
        mol_counts: Count of each molecule
        ff_name: Force field name
        ff_version: Force field version

    Returns:
        8-character hash string
    """
    data = {
        "mol_ids": sorted(mol_ids),
        "mol_counts": {k: mol_counts[k] for k in sorted(mol_counts.keys())},
        "ff_name": ff_name,
        "ff_version": ff_version,
    }
    return compute_content_hash(data, length=8)


def compute_protocol_hash(
    tier: str,
    stabilization_steps: list[dict],
    ff_type: str,
    temperature_k: float,
    pressure_atm: float,
) -> str:
    """
    Compute protocol hash for reproducibility.

    Args:
        tier: Run tier name
        stabilization_steps: List of step configurations
        ff_type: Force field type
        temperature_k: Temperature in Kelvin
        pressure_atm: Pressure in atm

    Returns:
        8-character hash string
    """
    data = {
        "tier": tier,
        "stabilization_steps": stabilization_steps,
        "ff_type": ff_type,
        "temperature_k": temperature_k,
        "pressure_atm": pressure_atm,
    }
    return compute_content_hash(data, length=8)


def compute_composition_hash(composition: dict[str, float], target_atoms: int, seed: int) -> str:
    """
    Compute composition hash for reproducibility.

    Args:
        composition: Target composition (wt%)
        target_atoms: Target atom count
        seed: Random seed

    Returns:
        8-character hash string
    """
    # Round composition values to avoid floating point issues
    rounded_comp = {k: round(v, 4) for k, v in sorted(composition.items())}
    data = {
        "composition": rounded_comp,
        "target_atoms": target_atoms,
        "seed": seed,
    }
    return compute_content_hash(data, length=8)
