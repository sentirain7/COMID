"""Inorganic material parameterization service.

This module provides site-specific parameterization for inorganic additives
(e.g., SiO2, NanoClay) using profiles defined in inorganic_profiles.yaml.

The service:
1. Loads profile definitions from the SSOT YAML file
2. Infers site types from topology connectivity (1-based atom indices)
3. Assigns charges from CLAYFF
4. Returns LJ and bonded coefficients from INTERFACE FF / Emami et al.

References:
    - CLAYFF: Cygan et al., J. Phys. Chem. B 2004, 108, 1255
    - INTERFACE FF: Heinz et al., Langmuir 2013, 29, 1754
    - Silica surface: Emami et al., Chem. Mater. 2014, 26, 2647
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from common.logging import get_logger
from common.pathing import get_project_root

logger = get_logger("forcefield.inorganic_parameter_service")


class InorganicParameterizationError(Exception):
    """Raised when inorganic parameterization fails."""

    pass


@dataclass
class SiteAssignment:
    """Site assignment for a single atom."""

    atom_index: int  # 1-based
    element: str
    site_type: str
    charge: float


@dataclass
class InorganicAssignmentResult:
    """Result of inorganic parameterization."""

    profile_id: str
    site_assignments: list[SiteAssignment]
    total_charge: float
    atom_type_coeffs: dict[str, dict[str, float]]
    bond_type_coeffs: dict[str, dict[str, float]]
    angle_type_coeffs: dict[str, dict[str, float]]
    dihedral_policy: str = "strict"  # "strict" or "allow_default_fallback"
    bonded_philosophy: str = "full"  # "full" or "nonbonded_lattice"


class InorganicParameterService:
    """Site-specific parameterization for inorganic additives.

    This service assigns site-specific charges and force field parameters
    to inorganic molecules based on their topology connectivity.

    The atom indices in MolTopology (from mol_types.py) are 1-based,
    which is verified by the MolBond.atom1/atom2 fields.

    Example:
        >>> from forcefield.inorganic_parameter_service import InorganicParameterService
        >>> service = InorganicParameterService()
        >>> result = service.assign(topology, additive_def)
        >>> print(result.total_charge)  # Should be ~0 for neutral system
    """

    def __init__(self, profiles_path: Path | None = None):
        """Initialize service with profile definitions.

        Args:
            profiles_path: Path to inorganic_profiles.yaml.
                           Defaults to data/forcefields/inorganic_profiles.yaml.
        """
        self._profiles_path = profiles_path or (
            get_project_root() / "data" / "forcefields" / "inorganic_profiles.yaml"
        )
        self._profiles: dict[str, dict[str, Any]] = {}
        self._load_profiles()

    def _load_profiles(self) -> None:
        """Load profile definitions from YAML file."""
        if not self._profiles_path.exists():
            raise InorganicParameterizationError(
                f"Inorganic profiles not found: {self._profiles_path}"
            )

        with open(self._profiles_path) as f:
            data = yaml.safe_load(f)

        self._profiles = data.get("profiles", {})
        logger.debug(f"Loaded {len(self._profiles)} inorganic profiles")

    def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        """Get profile by ID.

        Args:
            profile_id: Profile identifier (e.g., "silica_hydroxylated_v1")

        Returns:
            Profile dict or None if not found
        """
        return self._profiles.get(profile_id)

    def get_element_lj_from_profile(
        self,
        profile_id: str,
        element: str,
    ) -> dict[str, float] | None:
        """Get LJ parameters for an element from a profile.

        This is a convenience method for layered structure builds where
        element-based LJ lookup is needed (not site-specific).

        Args:
            profile_id: Profile identifier (e.g., "silica_hydroxylated_v1")
            element: Element symbol (e.g., "Si", "O", "H")

        Returns:
            Dict with 'epsilon', 'sigma', 'mass' if found, None otherwise
        """
        profile = self._profiles.get(profile_id)
        if not profile or profile.get("status") != "active":
            return None

        site_rules = profile.get("site_rules", {})
        atom_types = profile.get("atom_types", {})

        # Find first site_type matching the element
        for site_type, rule in site_rules.items():
            if rule.get("element") == element and site_type in atom_types:
                return dict(atom_types[site_type])

        return None

    def get_all_element_lj_from_active_profiles(self) -> dict[str, dict[str, float]]:
        """Get element -> LJ mapping from all active profiles.

        .. deprecated::
            Use get_lj_for_profile() instead for profile-aware lookups.
            This method loses profile identity (first-match wins) and will
            be removed in a future version.

        Returns:
            Dict mapping element symbol to LJ params (first match wins)

        Warns:
            DeprecationWarning: This method is deprecated.
        """
        import warnings

        warnings.warn(
            "get_all_element_lj_from_active_profiles() is deprecated. "
            "Use get_lj_for_profile(profile_id, element) or "
            "get_element_lj_from_profile(profile_id, element) instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        result: dict[str, dict[str, float]] = {}

        for _profile_id, profile in self._profiles.items():
            if profile.get("status") != "active":
                continue

            site_rules = profile.get("site_rules", {})
            atom_types = profile.get("atom_types", {})

            for site_type, rule in site_rules.items():
                elem = rule.get("element")
                if elem and elem not in result and site_type in atom_types:
                    result[elem] = dict(atom_types[site_type])

        return result

    def get_lj_for_profile(
        self,
        profile_id: str,
        element: str,
    ) -> dict[str, float] | None:
        """Get LJ parameters for specific profile and element.

        This is the preferred profile-aware lookup method that preserves
        profile identity for source tracking and reproducibility.

        Args:
            profile_id: Profile identifier (e.g., "silica_hydroxylated_v1")
            element: Element symbol (e.g., "Si", "O", "H")

        Returns:
            Dict with 'epsilon', 'sigma', 'mass' if found, None otherwise
        """
        return self.get_element_lj_from_profile(profile_id, element)

    def is_profile_active(self, profile_id: str) -> bool:
        """Check if profile is active (usable for builds).

        Args:
            profile_id: Profile identifier

        Returns:
            True if profile exists and has status "active"
        """
        profile = self._profiles.get(profile_id)
        if not profile:
            return False
        return profile.get("status") == "active"

    def assign(
        self,
        topology: Any,  # MolTopology from builder.mol_types
        additive_def: dict[str, Any],
    ) -> InorganicAssignmentResult:
        """Assign site-specific parameters to topology atoms.

        This method:
        1. Validates the additive is not blocked
        2. Loads the profile from YAML
        3. Builds adjacency from topology bonds (1-based indices)
        4. Infers site types using neighbor patterns
        5. Assigns charges to topology atoms (mutates in place)
        6. Returns coefficient dictionaries for MolTopologyBuilder override

        Args:
            topology: MolTopology instance with atoms and bonds
            additive_def: Raw additive definition from additives.yaml

        Returns:
            InorganicAssignmentResult with assignments and coefficients

        Raises:
            InorganicParameterizationError: If blocked, inactive, or assignment fails
        """
        # Extract parameterization config
        param = additive_def.get("parameterization", {})
        status = param.get("status", "active")
        profile_id = param.get("profile_id")
        mol_id = additive_def.get("short_name", additive_def.get("name", "unknown"))

        # Check for blocked_placeholder
        if status == "blocked_placeholder":
            raise InorganicParameterizationError(
                f"Additive '{mol_id}' is blocked_placeholder. "
                "Structure/metadata inconsistency must be resolved before build."
            )

        # Check for passthrough mode
        mode = param.get("mode", "inorganic_profile")
        if mode == "organic_gaff2_passthrough":
            raise InorganicParameterizationError(
                f"Additive '{mol_id}' uses organic_gaff2_passthrough mode. "
                "Use standard organic typing path instead of InorganicParameterService."
            )

        # Load and validate profile
        if not profile_id:
            raise InorganicParameterizationError(
                f"Additive '{mol_id}' has no profile_id in parameterization config."
            )

        profile = self._profiles.get(profile_id)
        if not profile:
            raise InorganicParameterizationError(
                f"Profile '{profile_id}' not found in inorganic_profiles.yaml."
            )

        profile_status = profile.get("status", "draft")
        if profile_status != "active":
            raise InorganicParameterizationError(
                f"Profile '{profile_id}' is not active (status: {profile_status}). "
                "Only active profiles can be used for builds."
            )

        # Build 1-based adjacency from topology bonds
        # MolBond.atom1 and atom2 are 1-indexed (see mol_types.py:33-34)
        atom_by_index: dict[int, Any] = {atom.index: atom for atom in topology.atoms}
        adj: dict[int, list[int]] = {atom.index: [] for atom in topology.atoms}

        for bond in topology.bonds:
            adj[bond.atom1].append(bond.atom2)
            adj[bond.atom2].append(bond.atom1)

        # Get site rules from profile
        site_rules = profile.get("site_rules", {})
        if not site_rules:
            raise InorganicParameterizationError(
                f"Profile '{profile_id}' has no site_rules defined."
            )

        # Assign site types to each atom
        assignments: list[SiteAssignment] = []

        for atom in topology.atoms:
            neighbor_indices = adj.get(atom.index, [])
            neighbor_elements = [atom_by_index[n].element for n in neighbor_indices]

            # Match site rule based on element and neighbor pattern
            site_type = self._match_site_rule(
                atom.element, neighbor_elements, site_rules, profile_id
            )
            rule = site_rules[site_type]
            charge = float(rule.get("charge", 0.0))

            # Record assignment
            assignments.append(
                SiteAssignment(
                    atom_index=atom.index,
                    element=atom.element,
                    site_type=site_type,
                    charge=charge,
                )
            )

            # Mutate topology atom in place
            atom.ff_type = site_type
            atom.charge = charge
            atom.charge_defined = True

        # Validate total charge (neutrality check)
        total_charge = sum(sa.charge for sa in assignments)
        tolerance = profile.get("validation", {}).get("neutrality_tolerance", 0.01)

        if abs(total_charge) > tolerance:
            raise InorganicParameterizationError(
                f"Charge neutrality violated for '{mol_id}': "
                f"total_charge={total_charge:.4f}e (tolerance: {tolerance})"
            )

        # Validate required elements
        required_elements = set(profile.get("validation", {}).get("required_elements", []))
        present_elements = {sa.element for sa in assignments}

        if required_elements and not required_elements.issubset(present_elements):
            missing = required_elements - present_elements
            raise InorganicParameterizationError(
                f"Required elements missing for '{mol_id}': {missing}"
            )

        # Log site distribution
        site_counts = Counter(sa.site_type for sa in assignments)
        logger.info(
            f"Assigned inorganic profile '{profile_id}' to '{mol_id}': "
            f"total_charge={total_charge:.4f}e, sites={dict(site_counts)}"
        )

        # Extract dihedral policy from profile validation section
        dihedral_policy = profile.get("validation", {}).get("dihedral_policy", "strict")

        # CLAYFF nonbonded lattice: filter bond/angle coefficients to only
        # include explicitly defined interactions (e.g., O-H hydroxyl bonds).
        # Lattice bonds (Si-O, Al-O, Mg-O) are intentionally absent in the
        # YAML because the crystal structure is maintained by Coulomb + LJ.
        bonded_philosophy = profile.get("bonded_philosophy", "full")
        raw_bond_types = dict(profile.get("bond_types", {}))
        raw_angle_types = dict(profile.get("angle_types", {}))

        if bonded_philosophy == "nonbonded_lattice":
            logger.info(
                "Profile '%s' uses nonbonded_lattice philosophy: "
                "only %d explicit bond type(s) and %d angle type(s) provided. "
                "Lattice atoms interact via nonbonded (LJ + Coulomb) only.",
                profile_id,
                len(raw_bond_types),
                len(raw_angle_types),
            )

        return InorganicAssignmentResult(
            profile_id=profile_id,
            site_assignments=assignments,
            total_charge=total_charge,
            atom_type_coeffs=dict(profile.get("atom_types", {})),
            bond_type_coeffs=raw_bond_types,
            angle_type_coeffs=raw_angle_types,
            dihedral_policy=dihedral_policy,
            bonded_philosophy=bonded_philosophy,
        )

    def _exact_match(self, pattern: dict[str, int], actual: Counter) -> bool:
        """Check if pattern exactly matches actual neighbor counts.

        This implements strict site matching where:
        1. All pattern elements must match their exact counts
        2. Pattern elements with count=0 mean "must NOT have that neighbor"
        3. Extra neighbors not in pattern cause match failure (closed-world assumption)

        Args:
            pattern: Expected neighbor counts (e.g., {Si: 2, H: 0})
            actual: Actual neighbor counts from topology

        Returns:
            True if exact match (pattern elements match AND no extra neighbors)

        Examples:
            pattern={Si: 2, H: 0}, actual={Si: 2} -> True (H:0 = H absent)
            pattern={Si: 2, H: 0}, actual={Si: 2, C: 1} -> False (extra C)
            pattern={Si: 1, H: 1}, actual={Si: 1, H: 1} -> True
        """
        # Check all pattern elements
        for elem, count in pattern.items():
            if actual.get(elem, 0) != count:
                return False

        # Check for extra neighbors not in pattern (closed-world)
        for elem, count in actual.items():
            if count > 0 and elem not in pattern:
                return False

        return True

    def _match_site_rule(
        self,
        element: str,
        neighbor_elements: list[str],
        rules: dict[str, dict[str, Any]],
        profile_id: str,
    ) -> str:
        """Match atom to site rule based on element and neighbor pattern.

        Priority:
        1. Exact multiset match (neighbor counts match exactly, no extra neighbors)
        2. Pattern with explicit zero counts (e.g., H:0 means "no H neighbors")
        3. Default rule for element (no neighbor_pattern specified)

        The matching uses closed-world assumption: atoms with neighbors not
        specified in any pattern will only match the default rule (if exists).

        Args:
            element: Atom element symbol (e.g., "Si", "O", "H")
            neighbor_elements: List of neighbor atom elements
            rules: Site rules from profile
            profile_id: Profile ID for error messages

        Returns:
            Site type name (e.g., "Si_tet", "O_br", "O_h")

        Raises:
            InorganicParameterizationError: If no matching rule found
        """
        neighbor_counts = Counter(neighbor_elements)

        # Filter rules for this element
        candidates = [
            (name, rule) for name, rule in rules.items() if rule.get("element") == element
        ]

        if not candidates:
            raise InorganicParameterizationError(
                f"No site rules for element '{element}' in profile '{profile_id}'"
            )

        # Try exact multiset match first (using closed-world _exact_match)
        for name, rule in candidates:
            pattern = rule.get("neighbor_pattern")
            if pattern is None or pattern == {}:
                continue  # No pattern or empty = default, try later

            if self._exact_match(pattern, neighbor_counts):
                return name

        # Try default rule (no pattern specified, or empty pattern)
        for name, rule in candidates:
            pattern = rule.get("neighbor_pattern")
            if pattern is None or pattern == {}:
                return name

        # No match found - provide detailed error
        raise InorganicParameterizationError(
            f"No matching site rule for element '{element}' with "
            f"neighbors {dict(neighbor_counts)} in profile '{profile_id}'. "
            f"Available rules: {[n for n, _ in candidates]}"
        )
