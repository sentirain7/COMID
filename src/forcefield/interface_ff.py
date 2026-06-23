"""INTERFACE Force Field — 무기물 원자의 LJ 파라미터 (계면 시뮬레이션용).

INTERFACE FF는 **유기물-무기물 계면(interface)** 상호작용을 정확히 재현하기 위해
무기물 쪽 LJ 파라미터를 실험 표면에너지에 fitting한 force field이다.

이름이 "interface"인 이유:
    파라미터 자체는 결정(무기물) 원자에 부여되지만, 파라미터의 **최적화 기준**이
    유기물-무기물 계면 물성(접촉각, 표면에너지, 벽개에너지)이다.
    즉, 결정 원자에 적용하되 계면을 정확히 기술하도록 설계된 FF.

적용 방식:
    - 바인더(유기물): GAFF2 (curated artifact) 파라미터 유지
    - 결정(무기물): 이 모듈의 INTERFACE FF LJ 파라미터 적용
    - 교차 상호작용: Lorentz-Berthelot mixing (pair_modify mix arithmetic)
    - 결정 원자는 frozen (fix setforce 0 0 0) → 결정 내부 bonded 항 불필요

UFF 대비 핵심 차이:
    - Si: ε = 0.0004 (UFF 0.402 대비 ~1000배 작음) → Coulomb 지배 물리 반영
    - O:  ε = 0.1554 (UFF 0.060 대비 ~2.6배 큼) → 표면 극성 정확 반영
    - UFF는 기체상 원자 데이터 기반 범용 FF로, 광물 표면에 부적합

Wave 4 SSOT note
================

The :data:`INTERFACE_FF_MINERAL_PARAMS` dict below is the runtime
authority used by all callers (layered_structures service,
interface_ff fallback path, additive_validator, ...). Wave 4 of the FF
SSOT initiative also extracts these values into
``data/forcefields/mineral_lj_catalog.yaml`` so the editable SSOT
lives as a yaml file. The two are kept identical by the regression
test ``tests/unit/test_interface_ff_yaml_equivalence.py``. The
hardcoded dict survives because:

1. Module import must NEVER depend on yaml being present (tmp_path
   tests, fresh checkouts before ``data/`` is populated).
2. Production environments that DO have the yaml are loaded at
   import time below, and any mismatch with the hardcoded dict is
   caught by the equivalence test before the build runs.

When updating an INTERFACE FF value, edit BOTH the yaml AND the
hardcoded dict. The equivalence test will fail if you forget either.

References:
    Heinz, H. et al. "Thermodynamically Consistent Force Fields for the
    Assembly of Inorganic, Organic, and Biological Nanostructures: The
    INTERFACE Force Field." Langmuir 2013, 29, 1754-1765.

    Emami, F. S. et al. "Force Field and a Surface Model Database for Silica
    to Simulate Interfacial Properties in Atomic Resolution."
    Chem. Mater. 2014, 26, 2647-2658.

    Heinz, H. et al. "Accurate Simulation of Surfaces and Interfaces of
    Face-Centered Cubic Metals Using 12-6 and 9-6 Lennard-Jones Potentials."
    J. Phys. Chem. C 2008, 112, 17281-17290.

    Mishra, R. K. et al. "cemff: A Force Field Database for Cementitious
    Materials Including Validations, Applications and Opportunities."
    Cem. Concr. Res. 2017, 102, 68-89.
"""

from __future__ import annotations

from common.logging import get_logger

logger = get_logger("forcefield.interface_ff")

# ---------------------------------------------------------------------------
# INTERFACE FF LJ parameters for mineral elements
# ---------------------------------------------------------------------------
# Keys are element symbols as they appear in crystal data files.
# Values: sigma (Angstrom), epsilon (kcal/mol).
#
# These are applied to crystal atom types that lack explicit Pair Coeffs
# in the combined layered data file (i.e., types not covered by the
# binder's organic FF coefficients).
#
# Wave 4: this dict is the runtime safety net. The editable SSOT lives
# at ``data/forcefields/mineral_lj_catalog.yaml`` and is loaded into
# ``INTERFACE_FF_MINERAL_PARAMS`` at module import time below. If the
# yaml is missing or malformed (tmp_path tests, fresh checkouts) the
# hardcoded values below are used as the fallback.
# ---------------------------------------------------------------------------

_INTERFACE_FF_HARDCODED_FALLBACK: dict[str, dict[str, float | str]] = {
    # ── Oxide / Silicate ──
    "Si": {
        "sigma": 3.302,
        "epsilon": 0.00040,
        "description": "INTERFACE FF Si (tetrahedral, quartz/silicate)",
    },
    "O": {
        "sigma": 3.166,
        "epsilon": 0.15540,
        "description": "INTERFACE FF O (oxide/carbonate surface)",
    },
    "Al": {
        "sigma": 3.300,
        "epsilon": 0.00500,
        "description": "INTERFACE FF Al (octahedral, corundum)",
    },
    "Ti": {
        "sigma": 3.175,
        "epsilon": 0.01700,
        "description": "INTERFACE FF Ti (rutile)",
    },
    "Fe": {
        "sigma": 2.912,
        "epsilon": 0.01300,
        "description": "INTERFACE FF Fe (hematite)",
    },
    "Zn": {
        "sigma": 2.763,
        "epsilon": 0.12400,
        "description": "INTERFACE FF Zn (zincite)",
    },
    # ── Carbonate ──
    "C": {
        "sigma": 3.296,
        "epsilon": 0.06800,
        "description": "INTERFACE FF C (carbonate CO3)",
    },
    # ── Alkaline earth / Alkali ──
    "Ca": {
        "sigma": 3.200,
        "epsilon": 0.10000,
        "description": "INTERFACE FF Ca (calcite/lime)",
    },
    "Mg": {
        "sigma": 3.021,
        "epsilon": 0.11100,
        "description": "INTERFACE FF Mg (periclase/magnesite)",
    },
    "Na": {
        "sigma": 2.983,
        "epsilon": 0.03000,
        "description": "INTERFACE FF Na (halite, ionic)",
    },
    "K": {
        "sigma": 3.812,
        "epsilon": 0.03500,
        "description": "INTERFACE FF K (sylvite, ionic)",
    },
    # ── Halide ──
    "Cl": {
        "sigma": 3.947,
        "epsilon": 0.22700,
        "description": "INTERFACE FF Cl (halide, ionic)",
    },
    # ── FCC Metals (Heinz et al. 2008, J. Phys. Chem. C 112, 17281) ──
    # 12-6 LJ fitted to reproduce experimental surface energies of FCC metals.
    # These are large epsilon values because the 12-6 potential must capture
    # metallic cohesion that is normally described by EAM/MEAM potentials.
    # For frozen crystal slabs, only the cross-interaction with binder matters.
    "Cu": {
        "sigma": 2.616,
        "epsilon": 4.7200,
        "description": "INTERFACE FF Cu (FCC metal surface)",
    },
    "Ni": {
        "sigma": 2.552,
        "epsilon": 5.6500,
        "description": "INTERFACE FF Ni (FCC metal surface)",
    },
    # ── Hydroxyl ──
    "H": {
        "sigma": 1.085,
        "epsilon": 0.01300,
        "description": "INTERFACE FF H (surface hydroxyl)",
    },
}


def _load_from_yaml_or_fallback() -> dict[str, dict[str, float | str]]:
    """Wave 4: prefer the yaml SSOT, fall back to the hardcoded dict.

    Production environments ship the yaml at
    ``data/forcefields/mineral_lj_catalog.yaml``. Test environments
    that override ``ASPHALT_PROJECT_ROOT`` to a tmp dir do not, and
    must fall through to the hardcoded fallback so module import does
    not break. The Wave 4 numerical-equivalence regression locks the
    two paths to the same value set.
    """
    try:
        from forcefield.mineral_lj_loader import (  # noqa: PLC0415
            MineralLJLoadError,
            load_interface_ff_params,
        )
    except Exception as exc:
        # Loader module itself failed to import — extreme fallback.
        logger.debug(
            "interface_ff: mineral_lj_loader import failed (%s); using hardcoded fallback",
            exc,
        )
        return _INTERFACE_FF_HARDCODED_FALLBACK

    try:
        loaded = load_interface_ff_params()
    except MineralLJLoadError as exc:
        logger.debug(
            "interface_ff: yaml SSOT not loadable (%s); using hardcoded fallback",
            exc,
        )
        return _INTERFACE_FF_HARDCODED_FALLBACK
    except Exception as exc:
        logger.warning(
            "interface_ff: unexpected error loading yaml SSOT (%s); using hardcoded fallback",
            exc,
        )
        return _INTERFACE_FF_HARDCODED_FALLBACK

    # Wave 4 contract: the yaml is the editable SSOT, so when it loads
    # cleanly it wins. The equivalence regression test ensures the two
    # paths are identical, so this swap is value-preserving in CI.
    return loaded


# Module-level runtime authority. Caller imports this name; the dict
# may be backed by either the yaml SSOT (production) or the hardcoded
# fallback (tmp_path tests / fresh checkouts).
INTERFACE_FF_MINERAL_PARAMS: dict[str, dict[str, float | str]] = _load_from_yaml_or_fallback()
