"""UFF-derived element fallback parameters for generic nonbonded coverage.

Wave 4 SSOT note
================

The :data:`UFF_ELEMENT_FALLBACKS` dict below is the runtime authority
used by ``contracts.policies.forcefield`` and the additive validator.
Wave 4 of the FF SSOT initiative also extracts these values into
``data/forcefields/mineral_lj_catalog.yaml`` (``uff_fallback`` section)
so the editable SSOT lives as a yaml file. The two are kept identical
by the regression test
``tests/unit/test_interface_ff_yaml_equivalence.py``.

The hardcoded dict survives because module import must not depend on
the yaml being present (tmp_path tests, fresh checkouts). When the
yaml IS present (production), it is loaded at import time and replaces
the hardcoded dict; the equivalence test makes that swap a no-op in CI.

When updating a UFF value, edit BOTH the yaml AND the hardcoded dict.
The equivalence test will fail if you forget either.

Reference:
    Rappé, A. K.; Casewit, C. J.; Colwell, K. S.; Goddard, W. A. III;
    Skiff, W. M. *J. Am. Chem. Soc.* 1992, 114, 10024–10035.
"""

from __future__ import annotations

from common.logging import get_logger

logger = get_logger("forcefield.uff_element_fallback")

_UFF_HARDCODED_FALLBACK: dict[str, dict[str, float | str]] = {
    "H": {
        "mass": 1.008000,
        "sigma": 2.886,
        "epsilon": 0.044,
        "charge": 0.0,
        "description": "UFF fallback (H_)",
    },
    "He": {
        "mass": 4.002602,
        "sigma": 2.362,
        "epsilon": 0.056,
        "charge": 0.0,
        "description": "UFF fallback (He4+4)",
    },
    "Li": {
        "mass": 6.940000,
        "sigma": 2.451,
        "epsilon": 0.025,
        "charge": 0.0,
        "description": "UFF fallback (Li)",
    },
    "Be": {
        "mass": 9.012183,
        "sigma": 2.745,
        "epsilon": 0.085,
        "charge": 0.0,
        "description": "UFF fallback (Be3+2)",
    },
    "B": {
        "mass": 10.810000,
        "sigma": 4.083,
        "epsilon": 0.180,
        "charge": 0.0,
        "description": "UFF fallback (B_2)",
    },
    "C": {
        "mass": 12.011000,
        "sigma": 3.851,
        "epsilon": 0.105,
        "charge": 0.0,
        "description": "UFF fallback (C_3)",
    },
    "N": {
        "mass": 14.007000,
        "sigma": 3.660,
        "epsilon": 0.069,
        "charge": 0.0,
        "description": "UFF fallback (N_3)",
    },
    "O": {
        "mass": 15.999000,
        "sigma": 3.500,
        "epsilon": 0.060,
        "charge": 0.0,
        "description": "UFF fallback (O_3)",
    },
    "F": {
        "mass": 18.998403,
        "sigma": 3.364,
        "epsilon": 0.050,
        "charge": 0.0,
        "description": "UFF fallback (F_)",
    },
    "Ne": {
        "mass": 20.179760,
        "sigma": 3.243,
        "epsilon": 0.042,
        "charge": 0.0,
        "description": "UFF fallback (Ne4+4)",
    },
    "Na": {
        "mass": 22.989769,
        "sigma": 2.983,
        "epsilon": 0.030,
        "charge": 0.0,
        "description": "UFF fallback (Na)",
    },
    "Mg": {
        "mass": 24.305000,
        "sigma": 3.021,
        "epsilon": 0.111,
        "charge": 0.0,
        "description": "UFF fallback (Mg3+2)",
    },
    "Al": {
        "mass": 26.981539,
        "sigma": 4.499,
        "epsilon": 0.505,
        "charge": 0.0,
        "description": "UFF fallback (Al3)",
    },
    "Si": {
        "mass": 28.085000,
        "sigma": 4.295,
        "epsilon": 0.402,
        "charge": 0.0,
        "description": "UFF fallback (Si3)",
    },
    "P": {
        "mass": 30.973762,
        "sigma": 4.147,
        "epsilon": 0.305,
        "charge": 0.0,
        "description": "UFF fallback (P_3+3)",
    },
    "S": {
        "mass": 32.060000,
        "sigma": 4.035,
        "epsilon": 0.274,
        "charge": 0.0,
        "description": "UFF fallback (S_3+2)",
    },
    "Cl": {
        "mass": 35.450000,
        "sigma": 3.947,
        "epsilon": 0.227,
        "charge": 0.0,
        "description": "UFF fallback (Cl)",
    },
    "Ar": {
        "mass": 39.948100,
        "sigma": 3.868,
        "epsilon": 0.185,
        "charge": 0.0,
        "description": "UFF fallback (Ar4+4)",
    },
    "K": {
        "mass": 39.098310,
        "sigma": 3.812,
        "epsilon": 0.035,
        "charge": 0.0,
        "description": "UFF fallback (K_)",
    },
    "Ca": {
        "mass": 40.078400,
        "sigma": 3.399,
        "epsilon": 0.238,
        "charge": 0.0,
        "description": "UFF fallback (Ca6+2)",
    },
    "Sc": {
        "mass": 44.955908,
        "sigma": 3.295,
        "epsilon": 0.019,
        "charge": 0.0,
        "description": "UFF fallback (Sc3+3)",
    },
    "Ti": {
        "mass": 47.867100,
        "sigma": 3.175,
        "epsilon": 0.017,
        "charge": 0.0,
        "description": "UFF fallback (Ti6+4)",
    },
    "V": {
        "mass": 50.941510,
        "sigma": 3.144,
        "epsilon": 0.016,
        "charge": 0.0,
        "description": "UFF fallback (V_3+5)",
    },
    "Cr": {
        "mass": 51.996160,
        "sigma": 3.023,
        "epsilon": 0.015,
        "charge": 0.0,
        "description": "UFF fallback (Cr6+3)",
    },
    "Mn": {
        "mass": 54.938044,
        "sigma": 2.961,
        "epsilon": 0.013,
        "charge": 0.0,
        "description": "UFF fallback (Mn6+2)",
    },
    "Fe": {
        "mass": 55.845200,
        "sigma": 2.912,
        "epsilon": 0.013,
        "charge": 0.0,
        "description": "UFF fallback (Fe6+2)",
    },
    "Co": {
        "mass": 58.933194,
        "sigma": 2.872,
        "epsilon": 0.014,
        "charge": 0.0,
        "description": "UFF fallback (Co6+3)",
    },
    "Ni": {
        "mass": 58.693440,
        "sigma": 2.834,
        "epsilon": 0.015,
        "charge": 0.0,
        "description": "UFF fallback (Ni4+2)",
    },
    "Cu": {
        "mass": 63.546300,
        "sigma": 3.495,
        "epsilon": 0.005,
        "charge": 0.0,
        "description": "UFF fallback (Cu3+1)",
    },
    "Zn": {
        "mass": 65.382000,
        "sigma": 2.763,
        "epsilon": 0.124,
        "charge": 0.0,
        "description": "UFF fallback (Zn3+2)",
    },
    "Ga": {
        "mass": 69.723100,
        "sigma": 4.383,
        "epsilon": 0.415,
        "charge": 0.0,
        "description": "UFF fallback (Ga3+3)",
    },
    "Ge": {
        "mass": 72.630800,
        "sigma": 4.280,
        "epsilon": 0.379,
        "charge": 0.0,
        "description": "UFF fallback (Ge3)",
    },
    "As": {
        "mass": 74.921596,
        "sigma": 4.230,
        "epsilon": 0.309,
        "charge": 0.0,
        "description": "UFF fallback (As3+3)",
    },
    "Se": {
        "mass": 78.971800,
        "sigma": 4.205,
        "epsilon": 0.291,
        "charge": 0.0,
        "description": "UFF fallback (Se3+2)",
    },
    "Br": {
        "mass": 79.904000,
        "sigma": 4.189,
        "epsilon": 0.251,
        "charge": 0.0,
        "description": "UFF fallback (Br)",
    },
    "Kr": {
        "mass": 83.798200,
        "sigma": 4.141,
        "epsilon": 0.220,
        "charge": 0.0,
        "description": "UFF fallback (Kr4+4)",
    },
    "Rb": {
        "mass": 85.467830,
        "sigma": 4.114,
        "epsilon": 0.040,
        "charge": 0.0,
        "description": "UFF fallback (Rb)",
    },
    "Sr": {
        "mass": 87.621000,
        "sigma": 3.641,
        "epsilon": 0.235,
        "charge": 0.0,
        "description": "UFF fallback (Sr6+2)",
    },
    "Y": {
        "mass": 88.905842,
        "sigma": 3.345,
        "epsilon": 0.072,
        "charge": 0.0,
        "description": "UFF fallback (Y_3+3)",
    },
    "Zr": {
        "mass": 91.224200,
        "sigma": 3.124,
        "epsilon": 0.069,
        "charge": 0.0,
        "description": "UFF fallback (Zr3+4)",
    },
    "Nb": {
        "mass": 92.906372,
        "sigma": 3.165,
        "epsilon": 0.059,
        "charge": 0.0,
        "description": "UFF fallback (Nb3+5)",
    },
    "Mo": {
        "mass": 95.951000,
        "sigma": 3.052,
        "epsilon": 0.056,
        "charge": 0.0,
        "description": "UFF fallback (Mo6+6)",
    },
    "Tc": {
        "mass": 98.000000,
        "sigma": 2.998,
        "epsilon": 0.048,
        "charge": 0.0,
        "description": "UFF fallback (Tc6+5)",
    },
    "Ru": {
        "mass": 101.072000,
        "sigma": 2.963,
        "epsilon": 0.056,
        "charge": 0.0,
        "description": "UFF fallback (Ru6+2)",
    },
    "Rh": {
        "mass": 102.905502,
        "sigma": 2.929,
        "epsilon": 0.053,
        "charge": 0.0,
        "description": "UFF fallback (Rh6+3)",
    },
    "Pd": {
        "mass": 106.421000,
        "sigma": 2.899,
        "epsilon": 0.048,
        "charge": 0.0,
        "description": "UFF fallback (Pd4+2)",
    },
    "Ag": {
        "mass": 107.868220,
        "sigma": 3.148,
        "epsilon": 0.036,
        "charge": 0.0,
        "description": "UFF fallback (Ag1+1)",
    },
    "Cd": {
        "mass": 112.414400,
        "sigma": 2.848,
        "epsilon": 0.228,
        "charge": 0.0,
        "description": "UFF fallback (Cd3+2)",
    },
    "In": {
        "mass": 114.818100,
        "sigma": 4.463,
        "epsilon": 0.599,
        "charge": 0.0,
        "description": "UFF fallback (In3+3)",
    },
    "Sn": {
        "mass": 118.710700,
        "sigma": 4.392,
        "epsilon": 0.567,
        "charge": 0.0,
        "description": "UFF fallback (Sn3)",
    },
    "Sb": {
        "mass": 121.760100,
        "sigma": 4.420,
        "epsilon": 0.449,
        "charge": 0.0,
        "description": "UFF fallback (Sb3+3)",
    },
    "Te": {
        "mass": 127.603000,
        "sigma": 4.470,
        "epsilon": 0.398,
        "charge": 0.0,
        "description": "UFF fallback (Te3+2)",
    },
    "I": {
        "mass": 126.904473,
        "sigma": 4.500,
        "epsilon": 0.339,
        "charge": 0.0,
        "description": "UFF fallback (I_)",
    },
    "Xe": {
        "mass": 131.293600,
        "sigma": 4.404,
        "epsilon": 0.332,
        "charge": 0.0,
        "description": "UFF fallback (Xe4+4)",
    },
    "Cs": {
        "mass": 132.905452,
        "sigma": 4.517,
        "epsilon": 0.045,
        "charge": 0.0,
        "description": "UFF fallback (Cs)",
    },
    "Ba": {
        "mass": 137.327700,
        "sigma": 3.703,
        "epsilon": 0.364,
        "charge": 0.0,
        "description": "UFF fallback (Ba6+2)",
    },
    "La": {
        "mass": 138.905477,
        "sigma": 3.522,
        "epsilon": 0.017,
        "charge": 0.0,
        "description": "UFF fallback (La3+3)",
    },
    "Ce": {
        "mass": 140.116100,
        "sigma": 3.556,
        "epsilon": 0.013,
        "charge": 0.0,
        "description": "UFF fallback (Ce6+3)",
    },
    "Pr": {
        "mass": 140.907662,
        "sigma": 3.606,
        "epsilon": 0.010,
        "charge": 0.0,
        "description": "UFF fallback (Pr6+3)",
    },
    "Nd": {
        "mass": 144.242300,
        "sigma": 3.575,
        "epsilon": 0.010,
        "charge": 0.0,
        "description": "UFF fallback (Nd6+3)",
    },
    "Pm": {
        "mass": 145.000000,
        "sigma": 3.547,
        "epsilon": 0.009,
        "charge": 0.0,
        "description": "UFF fallback (Pm6+3)",
    },
    "Sm": {
        "mass": 150.362000,
        "sigma": 3.520,
        "epsilon": 0.008,
        "charge": 0.0,
        "description": "UFF fallback (Sm6+3)",
    },
    "Eu": {
        "mass": 151.964100,
        "sigma": 3.493,
        "epsilon": 0.008,
        "charge": 0.0,
        "description": "UFF fallback (Eu6+3)",
    },
    "Gd": {
        "mass": 157.253000,
        "sigma": 3.368,
        "epsilon": 0.009,
        "charge": 0.0,
        "description": "UFF fallback (Gd6+3)",
    },
    "Tb": {
        "mass": 158.925352,
        "sigma": 3.451,
        "epsilon": 0.007,
        "charge": 0.0,
        "description": "UFF fallback (Tb6+3)",
    },
    "Dy": {
        "mass": 162.500100,
        "sigma": 3.428,
        "epsilon": 0.007,
        "charge": 0.0,
        "description": "UFF fallback (Dy6+3)",
    },
    "Ho": {
        "mass": 164.930332,
        "sigma": 3.409,
        "epsilon": 0.007,
        "charge": 0.0,
        "description": "UFF fallback (Ho6+3)",
    },
    "Er": {
        "mass": 167.259300,
        "sigma": 3.391,
        "epsilon": 0.007,
        "charge": 0.0,
        "description": "UFF fallback (Er6+3)",
    },
    "Tm": {
        "mass": 168.934222,
        "sigma": 3.374,
        "epsilon": 0.006,
        "charge": 0.0,
        "description": "UFF fallback (Tm6+3)",
    },
    "Yb": {
        "mass": 173.045100,
        "sigma": 3.355,
        "epsilon": 0.228,
        "charge": 0.0,
        "description": "UFF fallback (Yb6+3)",
    },
    "Lu": {
        "mass": 174.966810,
        "sigma": 3.640,
        "epsilon": 0.041,
        "charge": 0.0,
        "description": "UFF fallback (Lu6+3)",
    },
    "Hf": {
        "mass": 178.492000,
        "sigma": 3.141,
        "epsilon": 0.072,
        "charge": 0.0,
        "description": "UFF fallback (Hf3+4)",
    },
    "Ta": {
        "mass": 180.947882,
        "sigma": 3.170,
        "epsilon": 0.081,
        "charge": 0.0,
        "description": "UFF fallback (Ta3+5)",
    },
    "W": {
        "mass": 183.841000,
        "sigma": 3.069,
        "epsilon": 0.067,
        "charge": 0.0,
        "description": "UFF fallback (W_6+6)",
    },
    "Re": {
        "mass": 186.207100,
        "sigma": 2.954,
        "epsilon": 0.066,
        "charge": 0.0,
        "description": "UFF fallback (Re6+5)",
    },
    "Os": {
        "mass": 190.233000,
        "sigma": 3.120,
        "epsilon": 0.037,
        "charge": 0.0,
        "description": "UFF fallback (Os6+6)",
    },
    "Ir": {
        "mass": 192.217300,
        "sigma": 2.840,
        "epsilon": 0.073,
        "charge": 0.0,
        "description": "UFF fallback (Ir6+3)",
    },
    "Pt": {
        "mass": 195.084900,
        "sigma": 2.754,
        "epsilon": 0.080,
        "charge": 0.0,
        "description": "UFF fallback (Pt4+2)",
    },
    "Au": {
        "mass": 196.966569,
        "sigma": 3.293,
        "epsilon": 0.039,
        "charge": 0.0,
        "description": "UFF fallback (Au4+3)",
    },
    "Hg": {
        "mass": 200.592300,
        "sigma": 2.705,
        "epsilon": 0.385,
        "charge": 0.0,
        "description": "UFF fallback (Hg1+2)",
    },
    "Tl": {
        "mass": 204.380000,
        "sigma": 4.347,
        "epsilon": 0.680,
        "charge": 0.0,
        "description": "UFF fallback (Tl3+3)",
    },
    "Pb": {
        "mass": 207.210000,
        "sigma": 4.297,
        "epsilon": 0.663,
        "charge": 0.0,
        "description": "UFF fallback (Pb3)",
    },
    "Bi": {
        "mass": 208.980401,
        "sigma": 4.370,
        "epsilon": 0.518,
        "charge": 0.0,
        "description": "UFF fallback (Bi3+3)",
    },
    "Po": {
        "mass": 209.000000,
        "sigma": 4.709,
        "epsilon": 0.325,
        "charge": 0.0,
        "description": "UFF fallback (Po3+2)",
    },
    "At": {
        "mass": 210.000000,
        "sigma": 4.750,
        "epsilon": 0.284,
        "charge": 0.0,
        "description": "UFF fallback (At)",
    },
    "Rn": {
        "mass": 222.000000,
        "sigma": 4.765,
        "epsilon": 0.248,
        "charge": 0.0,
        "description": "UFF fallback (Rn4+4)",
    },
    "Fr": {
        "mass": 223.000000,
        "sigma": 4.900,
        "epsilon": 0.050,
        "charge": 0.0,
        "description": "UFF fallback (Fr)",
    },
    "Ra": {
        "mass": 226.000000,
        "sigma": 3.677,
        "epsilon": 0.404,
        "charge": 0.0,
        "description": "UFF fallback (Ra6+2)",
    },
    "Ac": {
        "mass": 227.000000,
        "sigma": 3.478,
        "epsilon": 0.033,
        "charge": 0.0,
        "description": "UFF fallback (Ac6+3)",
    },
    "Th": {
        "mass": 232.037740,
        "sigma": 3.396,
        "epsilon": 0.026,
        "charge": 0.0,
        "description": "UFF fallback (Th6+4)",
    },
    "Pa": {
        "mass": 231.035882,
        "sigma": 3.424,
        "epsilon": 0.022,
        "charge": 0.0,
        "description": "UFF fallback (Pa6+4)",
    },
    "U": {
        "mass": 238.028913,
        "sigma": 3.395,
        "epsilon": 0.022,
        "charge": 0.0,
        "description": "UFF fallback (U_6+4)",
    },
    "Np": {
        "mass": 237.000000,
        "sigma": 3.424,
        "epsilon": 0.019,
        "charge": 0.0,
        "description": "UFF fallback (Np6+4)",
    },
    "Pu": {
        "mass": 244.000000,
        "sigma": 3.424,
        "epsilon": 0.016,
        "charge": 0.0,
        "description": "UFF fallback (Pu6+4)",
    },
    "Am": {
        "mass": 243.000000,
        "sigma": 3.381,
        "epsilon": 0.014,
        "charge": 0.0,
        "description": "UFF fallback (Am6+4)",
    },
    "Cm": {
        "mass": 247.000000,
        "sigma": 3.326,
        "epsilon": 0.013,
        "charge": 0.0,
        "description": "UFF fallback (Cm6+3)",
    },
    "Bk": {
        "mass": 247.000000,
        "sigma": 3.339,
        "epsilon": 0.013,
        "charge": 0.0,
        "description": "UFF fallback (Bk6+3)",
    },
    "Cf": {
        "mass": 251.000000,
        "sigma": 3.313,
        "epsilon": 0.013,
        "charge": 0.0,
        "description": "UFF fallback (Cf6+3)",
    },
    "Es": {
        "mass": 252.000000,
        "sigma": 3.299,
        "epsilon": 0.012,
        "charge": 0.0,
        "description": "UFF fallback (Es6+3)",
    },
    "Fm": {
        "mass": 257.000000,
        "sigma": 3.286,
        "epsilon": 0.012,
        "charge": 0.0,
        "description": "UFF fallback (Fm6+3)",
    },
    "Md": {
        "mass": 258.000000,
        "sigma": 3.274,
        "epsilon": 0.011,
        "charge": 0.0,
        "description": "UFF fallback (Md6+3)",
    },
    "No": {
        "mass": 259.000000,
        "sigma": 3.248,
        "epsilon": 0.011,
        "charge": 0.0,
        "description": "UFF fallback (No6+3)",
    },
    "Lr": {
        "mass": 266.000000,
        "sigma": 3.236,
        "epsilon": 0.011,
        "charge": 0.0,
        "description": "UFF fallback (Lw6+3)",
    },
}


def _load_from_yaml_or_fallback() -> dict[str, dict[str, float | str]]:
    """Wave 4: prefer the yaml SSOT, fall back to the hardcoded dict."""
    try:
        from forcefield.mineral_lj_loader import (  # noqa: PLC0415
            MineralLJLoadError,
            load_uff_fallback_params,
        )
    except Exception as exc:
        logger.debug(
            "uff_element_fallback: mineral_lj_loader import failed (%s); using hardcoded fallback",
            exc,
        )
        return _UFF_HARDCODED_FALLBACK

    try:
        loaded = load_uff_fallback_params()
    except MineralLJLoadError as exc:
        logger.debug(
            "uff_element_fallback: yaml SSOT not loadable (%s); using hardcoded fallback",
            exc,
        )
        return _UFF_HARDCODED_FALLBACK
    except Exception as exc:
        logger.warning(
            "uff_element_fallback: unexpected error loading yaml SSOT (%s); "
            "using hardcoded fallback",
            exc,
        )
        return _UFF_HARDCODED_FALLBACK

    return loaded


# Module-level runtime authority. Caller imports this name; the dict
# may be backed by either the yaml SSOT (production) or the hardcoded
# fallback (tmp_path tests / fresh checkouts).
UFF_ELEMENT_FALLBACKS: dict[str, dict[str, float | str]] = _load_from_yaml_or_fallback()
