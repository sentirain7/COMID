"""
SMILES Utilities for Molecule Validation and Analysis.

Provides SMILES string validation, parsing, and property estimation
without requiring RDKit (uses regex-based parsing for basic validation).
"""

import re
from dataclasses import dataclass
from enum import Enum

from common.constants import ATOMIC_WEIGHTS
from common.hashing import compute_content_hash
from common.logging import get_logger

logger = get_logger("forcefield.smiles")


class SMILESError(Exception):
    """Error in SMILES processing."""

    pass


class ValidationLevel(Enum):
    """SMILES validation level."""

    BASIC = "basic"  # Syntax only
    STRUCTURE = "structure"  # Balanced brackets/rings
    FULL = "full"  # Attempt to parse atoms


@dataclass
class SMILESInfo:
    """Information extracted from SMILES string."""

    smiles: str
    smiles_hash: str
    is_valid: bool
    error_message: str | None = None

    # Estimated counts (may not be exact)
    carbon_count: int = 0
    hydrogen_count: int = 0
    nitrogen_count: int = 0
    oxygen_count: int = 0
    sulfur_count: int = 0
    phosphorus_count: int = 0
    halogen_count: int = 0

    # Structural features
    aromatic_ring_count: int = 0
    aliphatic_ring_count: int = 0
    has_stereochemistry: bool = False
    is_mixture: bool = False

    @property
    def heavy_atom_count(self) -> int:
        """Count of non-hydrogen atoms."""
        return (
            self.carbon_count
            + self.nitrogen_count
            + self.oxygen_count
            + self.sulfur_count
            + self.phosphorus_count
            + self.halogen_count
        )

    @property
    def estimated_molecular_weight(self) -> float:
        """Rough estimate of molecular weight."""
        mw = (
            self.carbon_count * ATOMIC_WEIGHTS["C"]
            + self.hydrogen_count * ATOMIC_WEIGHTS["H"]
            + self.nitrogen_count * ATOMIC_WEIGHTS["N"]
            + self.oxygen_count * ATOMIC_WEIGHTS["O"]
            + self.sulfur_count * ATOMIC_WEIGHTS["S"]
            + self.phosphorus_count * ATOMIC_WEIGHTS["P"]
            + self.halogen_count * 35  # Approximate for halogens
        )
        return round(mw, 2)


class SMILESValidator:
    """
    Validates SMILES strings using pattern-based parsing.

    Does not require RDKit - uses regex patterns for basic validation.
    For production use with chemical accuracy, RDKit should be used.
    """

    # Valid atom symbols
    ORGANIC_ATOMS = {"B", "C", "N", "O", "P", "S", "F", "Cl", "Br", "I"}
    AROMATIC_ATOMS = {"b", "c", "n", "o", "p", "s"}

    # Bond symbols
    BONDS = {"-", "=", "#", ":", "/", "\\"}

    # Regex patterns
    BRACKET_ATOM = re.compile(r"\[([^\]]+)\]")
    RING_CLOSURE = re.compile(r"%?\d+")
    ORGANIC_SUBSET = re.compile(r"[BCNOPSF]|Cl|Br|I")
    AROMATIC_SUBSET = re.compile(r"[bcnops]")

    def __init__(self, level: ValidationLevel = ValidationLevel.STRUCTURE):
        """
        Initialize validator.

        Args:
            level: Validation level
        """
        self.level = level

    def validate(self, smiles: str) -> SMILESInfo:
        """
        Validate a SMILES string.

        Args:
            smiles: SMILES string to validate

        Returns:
            SMILESInfo with validation results
        """
        if not smiles or not isinstance(smiles, str):
            return SMILESInfo(
                smiles=smiles or "",
                smiles_hash="",
                is_valid=False,
                error_message="Empty or invalid SMILES string",
            )

        smiles = smiles.strip()
        smiles_hash = compute_content_hash(smiles, length=16)

        # Check for mixture (multiple components)
        is_mixture = "." in smiles

        try:
            # Basic syntax check
            if self.level in [
                ValidationLevel.BASIC,
                ValidationLevel.STRUCTURE,
                ValidationLevel.FULL,
            ]:
                self._check_basic_syntax(smiles)

            # Structure check
            if self.level in [ValidationLevel.STRUCTURE, ValidationLevel.FULL]:
                self._check_structure(smiles)

            # Parse atoms and estimate properties
            info = self._parse_atoms(smiles)
            info.smiles = smiles
            info.smiles_hash = smiles_hash
            info.is_valid = True
            info.is_mixture = is_mixture

            return info

        except SMILESError as e:
            return SMILESInfo(
                smiles=smiles, smiles_hash=smiles_hash, is_valid=False, error_message=str(e)
            )

    def _check_basic_syntax(self, smiles: str) -> None:
        """Check basic SMILES syntax."""
        # Empty check
        if not smiles:
            raise SMILESError("Empty SMILES string")

        # Invalid characters
        valid_chars = set(
            "BCNOPSFIHbcnops"  # Atoms
            "[](){}."  # Brackets and separators
            "=#:-/\\"  # Bonds
            "+@"  # Charges and stereochemistry
            "0123456789%"  # Ring closures
        )

        for char in smiles:
            if char not in valid_chars and not char.isalpha():
                raise SMILESError(f"Invalid character: '{char}'")

    def _check_structure(self, smiles: str) -> None:
        """Check structural validity."""
        # Balanced brackets
        bracket_count = 0
        paren_count = 0

        for char in smiles:
            if char == "[":
                bracket_count += 1
            elif char == "]":
                bracket_count -= 1
            elif char == "(":
                paren_count += 1
            elif char == ")":
                paren_count -= 1

            if bracket_count < 0 or paren_count < 0:
                raise SMILESError("Unbalanced brackets or parentheses")

        if bracket_count != 0:
            raise SMILESError("Unbalanced square brackets")
        if paren_count != 0:
            raise SMILESError("Unbalanced parentheses")

        # Check ring closures are balanced (skip content inside brackets)
        ring_closures: dict[str, int] = {}
        i = 0
        in_bracket = False
        while i < len(smiles):
            char = smiles[i]

            if char == "[":
                in_bracket = True
            elif char == "]":
                in_bracket = False
            elif not in_bracket:
                if char == "%":
                    # Two-digit ring closure
                    if i + 2 < len(smiles):
                        ring_num = smiles[i + 1 : i + 3]
                        if ring_num.isdigit():
                            ring_closures[ring_num] = ring_closures.get(ring_num, 0) + 1
                            i += 2
                elif char.isdigit():
                    ring_closures[char] = ring_closures.get(char, 0) + 1
            i += 1

        for ring_num, count in ring_closures.items():
            if count % 2 != 0:
                raise SMILESError(f"Unbalanced ring closure: {ring_num}")

    def _parse_atoms(self, smiles: str) -> SMILESInfo:
        """Parse atoms from SMILES and estimate properties."""
        info = SMILESInfo(smiles="", smiles_hash="", is_valid=True)

        # Count aromatic atoms (for ring estimation)
        aromatic_count = sum(1 for c in smiles if c in self.AROMATIC_ATOMS)
        info.aromatic_ring_count = aromatic_count // 4  # Rough estimate

        # Check for stereochemistry
        info.has_stereochemistry = "@" in smiles or "/" in smiles or "\\" in smiles

        # Parse bracket atoms
        for match in self.BRACKET_ATOM.finditer(smiles):
            atom_spec = match.group(1)
            self._count_atom(atom_spec, info)

        # Remove bracket atoms for organic subset parsing
        remaining = self.BRACKET_ATOM.sub("", smiles)

        # Parse organic subset atoms
        i = 0
        while i < len(remaining):
            char = remaining[i]

            # Two-letter atoms
            if i + 1 < len(remaining):
                two_char = remaining[i : i + 2]
                if two_char in ["Cl", "Br"]:
                    info.halogen_count += 1
                    i += 2
                    continue

            # Single letter atoms
            if char == "C":
                info.carbon_count += 1
            elif char == "N":
                info.nitrogen_count += 1
            elif char == "O":
                info.oxygen_count += 1
            elif char == "S":
                info.sulfur_count += 1
            elif char == "P":
                info.phosphorus_count += 1
            elif char in "FI":
                info.halogen_count += 1
            elif char == "c":
                info.carbon_count += 1
            elif char == "n":
                info.nitrogen_count += 1
            elif char == "o":
                info.oxygen_count += 1
            elif char == "s":
                info.sulfur_count += 1
            elif char == "p":
                info.phosphorus_count += 1

            i += 1

        # Estimate hydrogens (very rough)
        info.hydrogen_count = self._estimate_hydrogens(info)

        return info

    def _count_atom(self, atom_spec: str, info: SMILESInfo) -> None:
        """Count atom from bracket notation."""
        # Extract element symbol
        match = re.match(r"(\d*)([A-Za-z][a-z]?)", atom_spec)
        if match:
            isotope, element = match.groups()
            element = element.capitalize()

            if element == "C":
                info.carbon_count += 1
            elif element == "N":
                info.nitrogen_count += 1
            elif element == "O":
                info.oxygen_count += 1
            elif element == "S":
                info.sulfur_count += 1
            elif element == "P":
                info.phosphorus_count += 1
            elif element in ["F", "Cl", "Br", "I"]:
                info.halogen_count += 1
            elif element == "H":
                # Explicit hydrogen
                h_count = re.search(r"H(\d*)", atom_spec)
                if h_count:
                    count = h_count.group(1)
                    info.hydrogen_count += int(count) if count else 1

    def _estimate_hydrogens(self, info: SMILESInfo) -> int:
        """Estimate hydrogen count based on valence rules."""
        # Very rough estimate based on typical valences
        # C: 4, N: 3, O: 2, S: 2
        h_count = 0
        h_count += info.carbon_count * 2  # Rough average for hydrocarbons
        h_count += info.nitrogen_count * 1
        h_count += info.oxygen_count * 0
        h_count += info.sulfur_count * 0

        # Adjust for aromatics (fewer H)
        h_count -= info.aromatic_ring_count * 4

        return max(0, h_count)


class MoleculeSearcher:
    """
    Searches and filters molecules based on various criteria.
    """

    def __init__(self, molecules: list[dict]):
        """
        Initialize searcher with molecule list.

        Args:
            molecules: List of molecule dictionaries
        """
        self.molecules = molecules
        self._build_index()

    def _build_index(self) -> None:
        """Build search indexes."""
        self._by_sara: dict[str, list[dict]] = {}
        self._by_id: dict[str, dict] = {}
        self._by_smiles_hash: dict[str, dict] = {}

        validator = SMILESValidator()

        for mol in self.molecules:
            # Index by SARA type (support both 'sara_type' and 'sara' field names)
            sara = mol.get("sara_type") or mol.get("sara", "unknown")
            if sara not in self._by_sara:
                self._by_sara[sara] = []
            self._by_sara[sara].append(mol)

            # Index by mol_id
            mol_id = mol.get("mol_id", "")
            if mol_id:
                self._by_id[mol_id] = mol

            # Index by SMILES hash
            smiles = mol.get("smiles", "")
            if smiles:
                info = validator.validate(smiles)
                if info.is_valid:
                    self._by_smiles_hash[info.smiles_hash] = mol

    def get_by_id(self, mol_id: str) -> dict | None:
        """Get molecule by ID."""
        return self._by_id.get(mol_id)

    def get_by_smiles(self, smiles: str) -> dict | None:
        """Get molecule by SMILES string."""
        validator = SMILESValidator()
        info = validator.validate(smiles)
        if info.is_valid:
            return self._by_smiles_hash.get(info.smiles_hash)
        return None

    def search_by_sara(self, sara_type: str) -> list[dict]:
        """Get all molecules of a SARA type."""
        return self._by_sara.get(sara_type, [])

    def search_by_mw_range(self, min_mw: float = 0, max_mw: float = float("inf")) -> list[dict]:
        """Search molecules by molecular weight range."""
        return [mol for mol in self.molecules if min_mw <= mol.get("molecular_weight", 0) <= max_mw]

    def search_by_atom_count(self, min_atoms: int = 0, max_atoms: int = float("inf")) -> list[dict]:
        """Search molecules by atom count range."""
        return [mol for mol in self.molecules if min_atoms <= mol.get("num_atoms", 0) <= max_atoms]

    def search_by_elements(
        self, required: set[str] | None = None, excluded: set[str] | None = None
    ) -> list[dict]:
        """Search molecules by elemental composition."""
        results = []
        validator = SMILESValidator()

        for mol in self.molecules:
            smiles = mol.get("smiles", "")
            if not smiles:
                continue

            info = validator.validate(smiles)
            if not info.is_valid:
                continue

            # Check required elements
            if required:
                has_all = True
                for elem in required:
                    if elem == "C" and info.carbon_count == 0:
                        has_all = False
                    elif elem == "N" and info.nitrogen_count == 0:
                        has_all = False
                    elif elem == "O" and info.oxygen_count == 0:
                        has_all = False
                    elif elem == "S" and info.sulfur_count == 0:
                        has_all = False
                if not has_all:
                    continue

            # Check excluded elements
            if excluded:
                has_excluded = False
                for elem in excluded:
                    if elem == "N" and info.nitrogen_count > 0:
                        has_excluded = True
                    elif elem == "O" and info.oxygen_count > 0:
                        has_excluded = True
                    elif elem == "S" and info.sulfur_count > 0:
                        has_excluded = True
                if has_excluded:
                    continue

            results.append(mol)

        return results

    def find_similar(self, smiles: str, max_results: int = 5) -> list[tuple[dict, float]]:
        """
        Find molecules with similar properties.

        Returns list of (molecule, similarity_score) tuples.
        """
        validator = SMILESValidator()
        target_info = validator.validate(smiles)

        if not target_info.is_valid:
            return []

        similarities = []

        for mol in self.molecules:
            mol_smiles = mol.get("smiles", "")
            if not mol_smiles:
                continue

            mol_info = validator.validate(mol_smiles)
            if not mol_info.is_valid:
                continue

            # Simple Tanimoto-like similarity based on atom counts
            score = self._compute_similarity(target_info, mol_info)
            similarities.append((mol, score))

        # Sort by similarity
        similarities.sort(key=lambda x: x[1], reverse=True)

        return similarities[:max_results]

    def _compute_similarity(self, info1: SMILESInfo, info2: SMILESInfo) -> float:
        """Compute simple similarity between two molecules."""
        # Feature vector
        v1 = [
            info1.carbon_count,
            info1.hydrogen_count,
            info1.nitrogen_count,
            info1.oxygen_count,
            info1.sulfur_count,
            info1.aromatic_ring_count * 10,  # Weight aromatics
        ]
        v2 = [
            info2.carbon_count,
            info2.hydrogen_count,
            info2.nitrogen_count,
            info2.oxygen_count,
            info2.sulfur_count,
            info2.aromatic_ring_count * 10,
        ]

        # Tanimoto-like coefficient
        intersection = sum(min(a, b) for a, b in zip(v1, v2, strict=False))
        union = sum(max(a, b) for a, b in zip(v1, v2, strict=False))

        if union == 0:
            return 0.0

        return intersection / union


def validate_smiles(smiles: str) -> SMILESInfo:
    """
    Convenience function to validate a SMILES string.

    Args:
        smiles: SMILES string to validate

    Returns:
        SMILESInfo with validation results
    """
    validator = SMILESValidator()
    return validator.validate(smiles)


def compute_smiles_hash(smiles: str) -> str:
    """
    Compute hash of SMILES string for caching.

    Args:
        smiles: SMILES string

    Returns:
        16-character hash string
    """
    return compute_content_hash(smiles.strip(), length=16)
