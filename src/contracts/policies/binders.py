"""
Default binder library for fallback when YAML unavailable.

This module contains the default binder compositions used as fallback
when the asphalt_binder.yaml configuration is not available.

Reference: Li & Greenfield (2014) - AAA-1 asphalt binder molecular model
"""

from typing import Any

# SARA component names (SSOT) — composition dict keys, iteration order fixed.
# tuple(고정 순서)인 이유: seed 기반 조성 샘플링이 성분 순회 순서에 의존하므로
# set을 쓰면 PYTHONHASHSEED에 따라 프로세스마다 결과가 달라진다.
SARA_COMPONENTS: tuple[str, ...] = ("asphaltene", "resin", "aromatic", "saturate")

# SARA prefix to category name mapping (used for molecule ID parsing)
DEFAULT_SARA_MAPPING: dict[str, str] = {
    "AR": "aromatic",
    "AS": "asphaltene",
    "RE": "resin",
    "SA": "saturate",
}

# Default binder library with compositions for AAA1, AAK1, AAM1
# Values are [X1, X2, X3] molecule counts
DEFAULT_BINDER_LIBRARY: dict[str, dict[str, Any]] = {
    "AAA1": {
        "description": "AAA-1 (Li & Greenfield 2014)",
        "sara_fractions": {
            "saturate": 0.111,
            "aromatic": 0.333,
            "resin": 0.444,
            "asphaltene": 0.111,
        },
        "composition": {
            "SA-Squalane": [4, 8, 12],
            "SA-Hopane": [4, 8, 12],
            "AR-PHPN": [11, 22, 33],
            "AR-DOCHN": [13, 26, 39],
            "RE-Quin": [4, 8, 12],
            "RE-Pyrid": [4, 8, 12],
            "RE-Thio": [4, 8, 12],
            "RE-Benzo": [15, 30, 45],
            "RE-Trim": [5, 10, 15],
            "AS-Pyrrole": [2, 4, 6],
            "AS-Phenol": [3, 6, 9],
            "AS-Thio": [3, 6, 9],
        },
    },
    "AAK1": {
        "description": "AAK-1 asphalt binder",
        "sara_fractions": {
            "saturate": 0.20,
            "aromatic": 0.40,
            "resin": 0.28,
            "asphaltene": 0.12,
        },
        "composition": {
            "SA-Squalane": [5, 10, 15],
            "SA-Hopane": [5, 10, 15],
            "AR-PHPN": [14, 28, 42],
            "AR-DOCHN": [16, 32, 48],
            "RE-Quin": [4, 8, 12],
            "RE-Pyrid": [4, 8, 12],
            "RE-Thio": [4, 8, 12],
            "RE-Benzo": [12, 24, 36],
            "RE-Trim": [4, 8, 12],
            "AS-Pyrrole": [2, 4, 6],
            "AS-Phenol": [3, 6, 9],
            "AS-Thio": [3, 6, 9],
        },
    },
    "AAM1": {
        "description": "AAM-1 asphalt binder",
        "sara_fractions": {
            "saturate": 0.15,
            "aromatic": 0.35,
            "resin": 0.32,
            "asphaltene": 0.18,
        },
        "composition": {
            "SA-Squalane": [4, 8, 12],
            "SA-Hopane": [4, 8, 12],
            "AR-PHPN": [12, 24, 36],
            "AR-DOCHN": [14, 28, 42],
            "RE-Quin": [5, 10, 15],
            "RE-Pyrid": [5, 10, 15],
            "RE-Thio": [4, 8, 12],
            "RE-Benzo": [14, 28, 42],
            "RE-Trim": [5, 10, 15],
            "AS-Pyrrole": [3, 6, 9],
            "AS-Phenol": [4, 8, 12],
            "AS-Thio": [4, 8, 12],
        },
    },
}


def get_default_binder_config() -> dict[str, Any]:
    """
    Get the default binder configuration for fallback use.

    Returns:
        Dictionary with 'binder_types' and 'sara_mapping' keys.
    """
    return {
        "binder_types": DEFAULT_BINDER_LIBRARY,
        "sara_mapping": DEFAULT_SARA_MAPPING,
    }
