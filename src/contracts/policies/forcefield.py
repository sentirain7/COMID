"""
Force Field Policy - SSOT for all force field parameters.

This module provides a centralized registry for force field configurations,
ensuring consistent parameter usage across the entire system.
"""

import importlib.util
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


class FFConditionKey(StrEnum):
    """SSOT for FF provenance condition keys stored in experiment_conditions.

    These keys are used as condition_key values in the experiment_conditions table.
    Centralizes the string constants to prevent typos and enable IDE autocomplete.
    """

    STACK_ID = "ff.stack_id"
    LANE_ID = "ff.lane_id"
    FAMILY_ORGANIC = "ff.family_organic"
    FAMILY_INORGANIC = "ff.family_inorganic"
    CHARGE_MODEL = "ff.charge_model"
    MIXING_RULE = "ff.mixing_rule"
    VALIDATION_LEVEL = "ff.validation_level"
    HAS_INORGANIC = "ff.has_inorganic"
    SOURCE_TAG = "ff.source_tag"


def is_valid_ff_condition_key(key: str) -> bool:
    """Check if a condition key is a valid FF provenance key.

    Args:
        key: The condition key string to validate.

    Returns:
        True if the key is a valid FFConditionKey, False otherwise.
    """
    try:
        FFConditionKey(key)
        return True
    except ValueError:
        return False


def list_ff_condition_keys() -> list[str]:
    """List all valid FF condition keys for documentation/validation.

    Returns:
        List of all FF condition key strings (9 keys).
    """
    return [k.value for k in FFConditionKey]


try:
    from forcefield.uff_element_fallback import UFF_ELEMENT_FALLBACKS
except ModuleNotFoundError:  # pragma: no cover - package execution fallback
    module_path = Path(__file__).resolve().parents[2] / "forcefield" / "uff_element_fallback.py"
    spec = importlib.util.spec_from_file_location("_standalone_uff_element_fallback", module_path)
    if spec is None or spec.loader is None:
        raise
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_standalone_uff_element_fallback", module)
    spec.loader.exec_module(module)
    UFF_ELEMENT_FALLBACKS = module.UFF_ELEMENT_FALLBACKS


@dataclass(frozen=True)
class AtomTypeParams:
    """Atom type parameters (LJ + charge)."""

    mass: float  # atomic mass
    epsilon: float  # LJ epsilon (kcal/mol)
    sigma: float  # LJ sigma (Angstrom)
    charge: float = 0.0  # partial charge
    element: str = ""  # element symbol
    description: str = ""  # type description


@dataclass(frozen=True)
class BondTypeParams:
    """Bond type parameters (harmonic)."""

    k: float  # force constant (kcal/mol/A^2)
    r0: float  # equilibrium distance (Angstrom)


@dataclass(frozen=True)
class AngleTypeParams:
    """Angle type parameters (harmonic)."""

    k: float  # force constant (kcal/mol/rad^2)
    theta0: float  # equilibrium angle (degrees)


@dataclass(frozen=True)
class DihedralTypeParams:
    """FF-neutral dihedral type parameters.

    Supports OPLS (4-coefficient), fourier (N-term), and harmonic styles.
    """

    style: str = "fourier"  # "fourier" | "opls" | "harmonic"
    coeffs: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)

    # Backward-compatible properties for OPLS-style access
    @property
    def k1(self) -> float:
        return self.coeffs[0] if len(self.coeffs) > 0 else 0.0

    @property
    def k2(self) -> float:
        return self.coeffs[1] if len(self.coeffs) > 1 else 0.0

    @property
    def k3(self) -> float:
        return self.coeffs[2] if len(self.coeffs) > 2 else 0.0

    @property
    def k4(self) -> float:
        return self.coeffs[3] if len(self.coeffs) > 3 else 0.0


@dataclass(frozen=True)
class ImproperTypeParams:
    """FF-neutral improper type parameters.

    Supports harmonic (OPLS) and cvff (GAFF2/AMBER) styles.
    """

    style: str = "cvff"  # "cvff" | "harmonic"
    coeffs: tuple[float, ...] = (0.0, 180.0)


@dataclass
class ForceFieldConfig:
    """Single force field configuration.

    Contains all parameters needed for a specific force field type.
    """

    name: str
    version: str
    description: str
    pair_style: str
    pair_cutoff: float
    enabled: bool = True

    # Parameter dictionaries
    atom_types: dict[str, AtomTypeParams] = field(default_factory=dict)
    bond_types: dict[str, BondTypeParams] = field(default_factory=dict)
    angle_types: dict[str, AngleTypeParams] = field(default_factory=dict)
    dihedral_types: dict[str, DihedralTypeParams] = field(default_factory=dict)
    element_fallbacks: dict[str, AtomTypeParams] = field(default_factory=dict)
    improper_types: dict[str, ImproperTypeParams] = field(default_factory=dict)

    # Runtime FF profile (SSOT for LAMMPS input generation)
    display_label: str = ""
    dihedral_style: str | None = None  # "opls" | "fourier" | "harmonic"
    improper_style: str | None = None  # "harmonic" | "cvff"
    special_bonds_lj: tuple[float, float, float] | None = None
    special_bonds_coul: tuple[float, float, float] | None = None
    native_mixing_rule: str | None = None  # "geometric" | "arithmetic"
    charge_provenance: str | None = None  # "cm1a_lbcc" | "am1_bcc"
    artifact_family: str | None = None  # "organic_gaff2"
    allowed_study_types: list[str] = field(default_factory=list)

    # Additional settings
    mixing_rules: dict[str, str] = field(default_factory=dict)
    special_bonds: str | None = None
    kspace_style: str | None = None

    def get_atom_params(self, atom_type: str) -> AtomTypeParams | None:
        """Get atom parameters by type name, including element fallbacks."""
        return self.atom_types.get(atom_type) or self.element_fallbacks.get(atom_type)

    def get_all_atom_types(self) -> dict[str, AtomTypeParams]:
        """Return explicit atom types plus fallback elements."""
        return {**self.element_fallbacks, **self.atom_types}

    def get_bond_params(self, bond_key: str) -> BondTypeParams | None:
        """Get bond parameters by key (e.g., 'CT-CT' or 'C-C')."""
        # Try exact match first
        if bond_key in self.bond_types:
            return self.bond_types[bond_key]
        # Try reversed order
        parts = bond_key.split("-")
        if len(parts) == 2:
            reversed_key = f"{parts[1]}-{parts[0]}"
            return self.bond_types.get(reversed_key)
        return None

    def get_angle_params(self, angle_key: str) -> AngleTypeParams | None:
        """Get angle parameters by key (e.g., 'CT-CT-CT')."""
        if angle_key in self.angle_types:
            return self.angle_types[angle_key]
        # Try reversed order
        parts = angle_key.split("-")
        if len(parts) == 3:
            reversed_key = f"{parts[2]}-{parts[1]}-{parts[0]}"
            return self.angle_types.get(reversed_key)
        return None

    def get_dihedral_params(self, dihedral_key: str) -> DihedralTypeParams | None:
        """Get dihedral parameters by key (e.g., 'CT-CT-CT-CT')."""
        if dihedral_key in self.dihedral_types:
            return self.dihedral_types[dihedral_key]
        # Try reversed order
        parts = dihedral_key.split("-")
        if len(parts) == 4:
            reversed_key = f"{parts[3]}-{parts[2]}-{parts[1]}-{parts[0]}"
            return self.dihedral_types.get(reversed_key)
        return None

    def get_improper_params(self, improper_key: str) -> ImproperTypeParams | None:
        """Get improper parameters by key."""
        if improper_key in self.improper_types:
            return self.improper_types[improper_key]
        parts = improper_key.split("-")
        if len(parts) == 4:
            reversed_key = f"{parts[3]}-{parts[2]}-{parts[1]}-{parts[0]}"
            return self.improper_types.get(reversed_key)
        return None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "pair_style": self.pair_style,
            "pair_cutoff": self.pair_cutoff,
            "enabled": self.enabled,
        }


class ForceFieldRegistry:
    """Registry for available force fields.

    Loads force field configurations from YAML and provides access
    to parameters. This is the SSOT for all force field data.
    """

    def __init__(self, registry_path: Path | None = None):
        """Initialize registry.

        Args:
            registry_path: Path to registry.yaml file. If None, uses default.
        """
        self._forcefields: dict[str, ForceFieldConfig] = {}
        self._default_ff: str | None = None

        if registry_path and registry_path.exists():
            self.load_from_yaml(registry_path)

    def load_from_yaml(self, path: Path) -> int:
        """Load force field configurations from YAML.

        Args:
            path: Path to YAML file

        Returns:
            Number of force fields loaded
        """
        with open(path) as f:
            data = yaml.safe_load(f)

        if not data or "forcefields" not in data:
            return 0

        self._default_ff = data.get("default", None)

        for ff_id, ff_data in data["forcefields"].items():
            config = self._parse_forcefield(ff_id, ff_data)
            self._forcefields[ff_id] = config

        return len(self._forcefields)

    def _parse_forcefield(self, ff_id: str, data: dict) -> ForceFieldConfig:
        """Parse force field configuration from dict."""
        # Parse atom types
        atom_types = {}
        for atom_id, params in data.get("atom_types", {}).items():
            atom_types[atom_id] = AtomTypeParams(
                mass=params.get("mass", 12.0),
                epsilon=params.get("epsilon", 0.0),
                sigma=params.get("sigma", 0.0),
                charge=params.get("charge", 0.0),
                element=params.get("element", ""),
                description=params.get("description", ""),
            )

        # Also parse from pair_coeffs section if present
        for atom_id, params in data.get("pair_coeffs", {}).items():
            if atom_id in atom_types:
                # Update existing with LJ params
                existing = atom_types[atom_id]
                atom_types[atom_id] = AtomTypeParams(
                    mass=existing.mass,
                    epsilon=params.get("epsilon", existing.epsilon),
                    sigma=params.get("sigma", existing.sigma),
                    charge=params.get("charge", existing.charge),
                    element=existing.element,
                    description=existing.description,
                )
            else:
                # Create new from pair_coeffs
                atom_types[atom_id] = AtomTypeParams(
                    mass=data.get("atom_types", {}).get(atom_id, {}).get("mass", 12.0),
                    epsilon=params.get("epsilon", 0.0),
                    sigma=params.get("sigma", 0.0),
                    charge=params.get("charge", 0.0),
                )

        element_fallbacks: dict[str, AtomTypeParams] = {}
        fallback_source = str(data.get("element_fallback_source", "")).strip().lower()

        # Fail-closed policy (v00.99.29): bulk_ff_gaff2 does not use UFF fallback.
        # All LJ parameters must come from explicit artifacts.
        if ff_id == "bulk_ff_gaff2" and fallback_source:
            from common.logging import get_logger

            logger = get_logger("contracts.policies.forcefield")
            logger.warning(
                "bulk_ff_gaff2: element_fallback_source='%s' ignored. "
                "Fail-closed policy requires explicit artifact LJ parameters.",
                fallback_source,
            )
            # Do NOT load UFF fallbacks for GAFF2
        elif fallback_source == "uff":
            # Other force fields may still use UFF fallback if configured
            for element, params in UFF_ELEMENT_FALLBACKS.items():
                element_fallbacks[element] = AtomTypeParams(
                    mass=float(params["mass"]),
                    epsilon=float(params["epsilon"]),
                    sigma=float(params["sigma"]),
                    charge=float(params.get("charge", 0.0)),
                    element=element,
                    description=str(params.get("description", "")),
                )

        for atom_id, params in data.get("element_fallbacks", {}).items():
            existing = element_fallbacks.get(atom_id)
            element_fallbacks[atom_id] = AtomTypeParams(
                mass=params.get("mass", existing.mass if existing else 12.0),
                epsilon=params.get("epsilon", existing.epsilon if existing else 0.0),
                sigma=params.get("sigma", existing.sigma if existing else 0.0),
                charge=params.get("charge", existing.charge if existing else 0.0),
                element=params.get("element", atom_id),
                description=params.get("description", ""),
            )

        # Parse bond types
        bond_types = {}
        for bond_id, params in data.get("bond_coeffs", {}).items():
            bond_types[bond_id] = BondTypeParams(
                k=params.get("k", 300.0),
                r0=params.get("r0", 1.5),
            )

        # Parse angle types
        angle_types = {}
        for angle_id, params in data.get("angle_coeffs", {}).items():
            angle_types[angle_id] = AngleTypeParams(
                k=params.get("k", 50.0),
                theta0=params.get("theta0", 109.5),
            )

        # Parse dihedral types (FF-neutral: style + coeffs)
        dihedral_types = {}
        for dih_id, params in data.get("dihedral_coeffs", {}).items():
            style = params.get("style", "opls")
            if style == "opls":
                coeffs = (
                    params.get("V1", params.get("k1", 0.0)),
                    params.get("V2", params.get("k2", 0.0)),
                    params.get("V3", params.get("k3", 0.0)),
                    params.get("V4", params.get("k4", 0.0)),
                )
            elif style == "fourier":
                terms = params.get("terms", [])
                coeffs = tuple(v for term in terms for v in (term["k"], term["d"], term["n"]))
            elif style == "harmonic":
                coeffs = (
                    params.get("k", 0.0),
                    params.get("d", 1),
                    params.get("n", 1),
                )
            else:
                coeffs = tuple(params.get("coeffs", (0.0,)))
            dihedral_types[dih_id] = DihedralTypeParams(style=style, coeffs=coeffs)

        # Parse improper types (FF-neutral: style + coeffs)
        improper_types: dict[str, ImproperTypeParams] = {}
        for imp_id, params in data.get("improper_coeffs", {}).items():
            style = params.get("style", "harmonic")
            if style == "harmonic":
                coeffs = (
                    params.get("k", 0.0),
                    params.get("chi0", params.get("phi0", 180.0)),
                )
            elif style == "cvff":
                coeffs = (
                    params.get("k", 0.0),
                    params.get("d", -1),
                    params.get("n", 2),
                )
            else:
                coeffs = tuple(params.get("coeffs", (0.0,)))
            improper_types[imp_id] = ImproperTypeParams(style=style, coeffs=coeffs)

        return ForceFieldConfig(
            name=data.get("name", ff_id),
            version=data.get("version", "1.0"),
            description=data.get("description", ""),
            pair_style=data.get("pair_style", "lj/cut"),
            pair_cutoff=data.get("pair_cutoff", 12.0),
            enabled=data.get("enabled", True),
            atom_types=atom_types,
            bond_types=bond_types,
            angle_types=angle_types,
            dihedral_types=dihedral_types,
            improper_types=improper_types,
            element_fallbacks=element_fallbacks,
            display_label=data.get("display_label", data.get("name", ff_id)),
            dihedral_style=data.get("dihedral_style"),
            improper_style=data.get("improper_style"),
            special_bonds_lj=tuple(data["special_bonds_lj"])
            if "special_bonds_lj" in data
            else None,
            special_bonds_coul=tuple(data["special_bonds_coul"])
            if "special_bonds_coul" in data
            else None,
            native_mixing_rule=data.get("native_mixing_rule"),
            charge_provenance=data.get("charge_provenance"),
            artifact_family=data.get("artifact_family"),
            allowed_study_types=data.get("allowed_study_types", []),
            mixing_rules=data.get("mixing_rules", {}),
            special_bonds=data.get("special_bonds"),
            kspace_style=data.get("kspace_style"),
        )

    def get(self, name: str) -> ForceFieldConfig | None:
        """Get force field by name.

        Args:
            name: Force field identifier (e.g., 'opls-aa', 'bulk_ff')

        Returns:
            ForceFieldConfig if found, None otherwise
        """
        return self._forcefields.get(name)

    def get_default(self) -> ForceFieldConfig | None:
        """Get the default force field."""
        if self._default_ff:
            return self.get(self._default_ff)
        # Fall back to first enabled FF
        for ff in self._forcefields.values():
            if ff.enabled:
                return ff
        return None

    def list_available(self) -> list[dict]:
        """List available force fields for API/UI.

        Returns:
            List of dicts with name, version, description for enabled FFs
        """
        return [
            {
                "name": ff.name,
                "version": ff.version,
                "description": ff.description,
                "pair_style": ff.pair_style,
            }
            for ff in self._forcefields.values()
            if ff.enabled
        ]

    def list_all(self) -> list[str]:
        """List all force field identifiers."""
        return list(self._forcefields.keys())

    def is_available(self, name: str) -> bool:
        """Check if a force field is available and enabled."""
        ff = self.get(name)
        return ff is not None and ff.enabled

    def __len__(self) -> int:
        """Return number of loaded force fields."""
        return len(self._forcefields)

    def __contains__(self, name: str) -> bool:
        """Check if force field exists."""
        return name in self._forcefields


_FF_DISPLAY_LABEL_MAP: dict[str, str] = {
    "bulk_ff_gaff2": "GAFF2",
    "reaxff": "ReaxFF",
}


def get_ff_display_label(ff_type: str, registry: ForceFieldRegistry | None = None) -> str:
    """SSOT: ff_type string -> human-readable display label.

    Centralizes the mapping that was previously scattered across 7+ files.
    Falls back to ff_type itself if no registry match.
    """
    if registry is not None:
        config = registry.get(ff_type)
        if config and config.display_label:
            return config.display_label
    return _FF_DISPLAY_LABEL_MAP.get(ff_type, ff_type)


def get_ff_version(ff_type: str = "bulk_ff_gaff2") -> str:
    """SSOT: ff_type string -> registry version string.

    Replaces all hardcoded ``force_field_version="1.0"`` occurrences.
    """
    registry = get_default_ff_registry()
    config = registry.get(ff_type)
    return config.version if config else "unknown"


def build_ff_provenance(
    study_type: str,
    ff_type: str = "bulk_ff_gaff2",
    source_tag: str = "unknown",
    metadata_json: dict[str, Any] | None = None,
    protocol_request: Any | None = None,
    build_request: Any | None = None,
    *,
    organic_sources: list[dict[str, str]] | None = None,
    inorganic_sources: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build canonical FF provenance metadata + experiment conditions.

    Infers layered/crystal state from actual request objects and metadata,
    NOT from caller-supplied boolean flags.

    Returns:
        {"metadata": {ff_provenance dict}, "conditions": [condition dicts]}
    """
    registry = get_default_ff_registry()
    config = registry.get(ff_type)
    meta = metadata_json or {}

    # --- Infer system composition from actual data ---
    has_inorganic = study_type == "layer_bulkff"

    # From metadata (layered builds store primary_sources)
    deferred = meta.get("deferred_submission", {})
    if deferred:
        br = deferred.get("build_request", {})
        if br.get("crystal_layers") or br.get("n_crystal_layers"):
            has_inorganic = True

    ps = meta.get("primary_sources", {})
    if ps.get("crystal") or ps.get("n_crystal_layers"):
        has_inorganic = True

    # From build_request object (if available)
    if build_request is not None:
        if hasattr(build_request, "crystal_layers") and build_request.crystal_layers:
            has_inorganic = True
        if hasattr(build_request, "primary_sources"):
            bps = build_request.primary_sources or {}
            if bps.get("crystal") or bps.get("inorganic"):
                has_inorganic = True

    # --- Semantic stack_id ---
    _stack_map: dict[tuple[str, bool], str] = {
        ("bulk", False): "gaff2_am1bcc_v1",
        ("single_molecule_vacuum", False): "gaff2_am1bcc_v1",
        ("layer_bulkff", True): "gaff2_org__inorganic_profile__arith_v1",
        ("reaxff_validation", False): "reaxff_v1",
    }
    stack_id = _stack_map.get(
        (study_type, has_inorganic),
        f"{ff_type}_v{config.version}" if config else ff_type,
    )

    # Generator-aware stack override: if any organic source used fragment
    # fallback, switch to the fragment_fallback stack (research_only governance)
    # so the lower-confidence charges are firewalled from the validated ML
    # dataset.  Restored in v01.06.x (general-purpose SCF-failure automation).
    if organic_sources:
        _generators = {s.get("generator", "antechamber_am1bcc") for s in organic_sources}
        if "fragment_fallback_gaff2" in _generators:
            stack_id = "gaff2_fragment_fallback_v1"

    # --- Lane mapping ---
    _lane_map = {
        "bulk": "bulk_organic",
        "layer_bulkff": "dry_interface",
        "single_molecule_vacuum": "single_molecule_vacuum",
        "reaxff_validation": "reactive_validation",
    }
    lane_id = _lane_map.get(study_type, study_type)

    # --- Build provenance block ---
    provenance: dict[str, Any] = {
        "stack_id": stack_id,
        "lane_id": lane_id,
        "ff_family_organic": config.name.lower() if config else "unknown",
        "ff_family_inorganic": "inorganic_profile" if has_inorganic else None,
        "inorganic_charge_family": "clayff" if has_inorganic else None,
        "inorganic_vdw_family": "interface_ff" if has_inorganic else None,
        "charge_model": (config.charge_provenance or "am1_bcc") if config else "unknown",
        "mixing_rule": (config.native_mixing_rule or "arithmetic") if config else "arithmetic",
        "cross_interaction_rule": "arithmetic_mixing" if has_inorganic else None,
        "water_model": None,
        "ion_model": None,
        "special_bonds_lj": list(config.special_bonds_lj)
        if config and config.special_bonds_lj
        else [0, 0, 0.5],
        "special_bonds_coul": list(config.special_bonds_coul)
        if config and config.special_bonds_coul
        else [0, 0, 0.8333],
        "source_tag": source_tag,
        # Phase 3 extensions: per-molecule source trace
        "organic_sources": organic_sources or [],
        "inorganic_sources": inorganic_sources or [],
    }

    # Derive validation_level from stack_governance if available
    try:
        from contracts.policies.stack_governance import get_validation_level

        provenance["validation_level"] = get_validation_level(stack_id)
    except Exception:
        provenance["validation_level"] = "research_only"

    # Derive aggregated generation_profiles from organic_sources
    if organic_sources:
        provenance["generation_profiles"] = sorted(
            {s.get("generation_profile", "baseline") for s in organic_sources}
        )
    else:
        provenance["generation_profiles"] = []

    # --- Conditions (query/index projection) ---
    # Use FFConditionKey enum for type safety and autocomplete, but output .value for DB storage
    _cond_map = {
        FFConditionKey.STACK_ID: stack_id,
        FFConditionKey.LANE_ID: lane_id,
        FFConditionKey.FAMILY_ORGANIC: provenance["ff_family_organic"],
        FFConditionKey.FAMILY_INORGANIC: provenance["ff_family_inorganic"],
        FFConditionKey.CHARGE_MODEL: provenance["charge_model"],
        FFConditionKey.MIXING_RULE: provenance["mixing_rule"],
        FFConditionKey.VALIDATION_LEVEL: provenance.get("validation_level"),
        FFConditionKey.HAS_INORGANIC: str(has_inorganic).lower(),
        FFConditionKey.SOURCE_TAG: source_tag,
    }
    conditions: list[dict[str, Any]] = []
    for key, val in _cond_map.items():
        if val is not None:
            conditions.append(
                {
                    "condition_key": key.value,  # .value preserves existing string format
                    "value_text": str(val),
                    "source": "ff_provenance",
                }
            )

    return {"metadata": provenance, "conditions": conditions}


def _get_default_registry_path() -> Path:
    """Get the default registry.yaml path."""
    # Navigate from src/contracts/policies/ to data/forcefields/
    current_dir = Path(__file__).parent
    project_root = current_dir.parent.parent.parent
    return project_root / "data" / "forcefields" / "registry.yaml"


# Default registry instance (lazy loaded)
_default_registry: ForceFieldRegistry | None = None


def get_default_ff_registry() -> ForceFieldRegistry:
    """Get the default ForceFieldRegistry instance.

    Creates and caches the registry on first access.
    """
    global _default_registry
    if _default_registry is None:
        registry_path = _get_default_registry_path()
        _default_registry = ForceFieldRegistry(registry_path)
    return _default_registry


# Convenience alias
DEFAULT_FF_REGISTRY = None  # Will be initialized on first import that needs it


def init_default_registry() -> ForceFieldRegistry:
    """Initialize and return the default registry."""
    global DEFAULT_FF_REGISTRY
    DEFAULT_FF_REGISTRY = get_default_ff_registry()
    return DEFAULT_FF_REGISTRY


# =============================================================================
# Method 1a (vacuum + extended cutoff) policy SSOT
# =============================================================================


@dataclass(frozen=True)
class VacuumExtendedCutoffPolicy:
    """Policy values for Method 1a vacuum-with-extended-cutoff E_intra.

    The numeric defaults live here (single source of truth) instead of being
    hard-coded inside ``protocols/lammps_force_field.py``.  Method 1a is
    activated by the ``ASPHALT_VACUUM_EXTENDED_CUTOFF`` env var; this dataclass
    only supplies the cutoff resolution rule.

    Attributes:
        min_cutoff_a: Floor cutoff in Å (clamps small molecules).
        extent_multiplier: Cutoff = max(min, multiplier × molecular_extent).
        legacy_default_cutoff_a: Method 1 legacy cutoff (12 Å) used when
            extended mode is disabled or extent is unknown.
    """

    min_cutoff_a: float = 50.0
    extent_multiplier: float = 2.0
    legacy_default_cutoff_a: float = 12.0


DEFAULT_VACUUM_EXTENDED_CUTOFF_POLICY = VacuumExtendedCutoffPolicy()
