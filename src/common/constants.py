"""
Common physical and chemical constants.

Provides shared constants used across multiple modules.
All values are from IUPAC 2016 standard atomic weights.
"""

# Standard atomic weights (g/mol) - IUPAC 2016
# Used for mass-based element identification in LAMMPS data files
ATOMIC_WEIGHTS: dict[str, float] = {
    "H": 1.008,
    "B": 10.811,
    "C": 12.011,
    "N": 14.007,
    "O": 15.9994,
    "F": 18.998,
    "Na": 22.9898,
    "Mg": 24.305,
    "Al": 26.982,
    "Si": 28.0855,
    "P": 30.974,
    "S": 32.065,
    "Cl": 35.450,
    "K": 39.098,
    "Ca": 40.078,
    "Ti": 47.867,
    "Fe": 55.845,
    "Ni": 58.6934,
    "Cu": 63.546,
    "Zn": 65.38,
    "Br": 79.904,
    "I": 126.904,
}
