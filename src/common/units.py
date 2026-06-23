"""
Unit conversion utilities - SSOT for unit handling.

All sessions must use these functions for unit conversions.
"""

# Physical constants
AVOGADRO = 6.02214076e23  # mol^-1
BOLTZMANN = 1.380649e-23  # J/K
ANGSTROM_TO_CM = 1e-8
ANGSTROM_TO_M = 1e-10
KCAL_TO_J = 4184.0
ATM_TO_PA = 101325.0
BAR_TO_PA = 100000.0
FS_TO_PS = 0.001
PS_TO_NS = 0.001

# CED conversion: 1 kcal/(mol·Å³) → MJ/m³
# = KCAL_TO_J / (AVOGADRO × ANGSTROM_TO_M³) / 1e6
# = 4184 / (6.022e23 × 1e-30) / 1e6 = 6947.7
KCAL_MOL_A3_TO_MJ_M3 = KCAL_TO_J / (AVOGADRO * ANGSTROM_TO_M**3) / 1e6


class UnitConverter:
    """Unit conversion utility class."""

    # Energy conversions (all relative to kcal/mol)
    ENERGY_FACTORS = {
        "kcal/mol": 1.0,
        "kJ/mol": 4.184,
        "eV": 0.0433641,  # per atom
        "J/mol": 4184.0,
        "MJ/m3": None,  # Needs volume
    }

    # Pressure conversions (all relative to atm)
    PRESSURE_FACTORS = {
        "atm": 1.0,
        "bar": 1.01325,
        "Pa": 101325.0,
        "kPa": 101.325,
        "MPa": 0.101325,
        "GPa": 0.000101325,
    }

    # Density conversions (all relative to g/cm3)
    DENSITY_FACTORS = {
        "g/cm3": 1.0,
        "g/cc": 1.0,  # Backward compatibility alias
        "kg/m3": 1000.0,
        "g/mL": 1.0,
    }

    # Time conversions (all relative to ps)
    TIME_FACTORS = {
        "fs": 0.001,
        "ps": 1.0,
        "ns": 1000.0,
        "us": 1000000.0,
        "ms": 1e9,
        "s": 1e12,
    }

    # Length conversions (all relative to Angstrom)
    LENGTH_FACTORS = {
        "angstrom": 1.0,
        "A": 1.0,
        "nm": 10.0,
        "um": 10000.0,
        "mm": 1e7,
        "cm": 1e8,
        "m": 1e10,
    }

    @classmethod
    def convert(cls, value: float, from_unit: str, to_unit: str, category: str) -> float:
        """
        Generic unit conversion.

        Args:
            value: Value to convert
            from_unit: Source unit
            to_unit: Target unit
            category: Unit category (energy, pressure, etc.)

        Returns:
            Converted value
        """
        factors: dict[str, dict[str, float | None]] = {
            "energy": cls.ENERGY_FACTORS,
            "pressure": cls.PRESSURE_FACTORS,  # type: ignore[dict-item]
            "density": cls.DENSITY_FACTORS,  # type: ignore[dict-item]
            "time": cls.TIME_FACTORS,  # type: ignore[dict-item]
            "length": cls.LENGTH_FACTORS,  # type: ignore[dict-item]
        }

        if category not in factors:
            raise ValueError(f"Unknown category: {category}")

        unit_factors = factors[category]

        if from_unit not in unit_factors:
            raise ValueError(f"Unknown {category} unit: {from_unit}")
        if to_unit not in unit_factors:
            raise ValueError(f"Unknown {category} unit: {to_unit}")

        from_factor = unit_factors[from_unit]
        to_factor = unit_factors[to_unit]

        if from_factor is None or to_factor is None:
            raise ValueError(f"Conversion not supported: {from_unit} -> {to_unit}")

        return value * float(from_factor) / float(to_factor)


def convert_energy(value: float, from_unit: str, to_unit: str) -> float:
    """
    Convert energy units.

    Args:
        value: Energy value
        from_unit: Source unit
        to_unit: Target unit

    Returns:
        Converted value
    """
    return UnitConverter.convert(value, from_unit, to_unit, "energy")


def convert_pressure(value: float, from_unit: str, to_unit: str) -> float:
    """
    Convert pressure units.

    Args:
        value: Pressure value
        from_unit: Source unit
        to_unit: Target unit

    Returns:
        Converted value
    """
    return UnitConverter.convert(value, from_unit, to_unit, "pressure")


def convert_density(value: float, from_unit: str, to_unit: str) -> float:
    """
    Convert density units.

    Args:
        value: Density value
        from_unit: Source unit
        to_unit: Target unit

    Returns:
        Converted value
    """
    return UnitConverter.convert(value, from_unit, to_unit, "density")


def convert_time(value: float, from_unit: str, to_unit: str) -> float:
    """
    Convert time units.

    Args:
        value: Time value
        from_unit: Source unit
        to_unit: Target unit

    Returns:
        Converted value
    """
    return UnitConverter.convert(value, from_unit, to_unit, "time")


def energy_to_ced(e_cohesive: float, volume_angstrom3: float, e_unit: str = "kcal/mol") -> float:
    """Convert cohesive energy density to MJ/m³.

    Args:
        e_cohesive: Cohesive energy in LAMMPS energy units
            (E_total - sum(n_i * E_intra_i), typically negative).
        volume_angstrom3: System volume in Angstrom³.
        e_unit: Energy unit (only "kcal/mol" supported).

    Returns:
        CED in MJ/m³ (positive value: sign is flipped internally).
    """
    if e_unit != "kcal/mol":
        raise ValueError(f"Unsupported energy unit: {e_unit}")
    if volume_angstrom3 <= 0:
        return 0.0
    # e_cohesive is typically negative (intermolecular attractions).
    # CED is a positive material property: CED = -e_cohesive / V * factor
    return -(e_cohesive / volume_angstrom3) * KCAL_MOL_A3_TO_MJ_M3


def volume_to_density(mass_g_per_mol: float, n_molecules: int, volume_angstrom3: float) -> float:
    """
    Calculate density from mass and volume.

    Args:
        mass_g_per_mol: Total mass in g/mol
        n_molecules: Number of molecules
        volume_angstrom3: Volume in Angstrom³

    Returns:
        Density in g/cm3
    """
    # Total mass in grams
    mass_g = (mass_g_per_mol * n_molecules) / AVOGADRO

    # Volume in cc (cm³)
    volume_cc = volume_angstrom3 * (ANGSTROM_TO_CM**3)

    return mass_g / volume_cc
