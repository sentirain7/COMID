"""Test helpers for injecting GAFF2 artifact-derived atom_types in unit tests.

GAFF2 fail-closed policy (v00.99.29) intentionally keeps
``bulk_ff_gaff2.atom_types`` and ``bulk_ff_gaff2.element_fallbacks`` empty in
``data/forcefields/registry.yaml``.  Production receives atom_types from
per-molecule artifacts (antechamber-generated frcmod/prmtop), not the registry.

Tests that exercise atom resolution downstream of the registry must inject
those atom_types explicitly.  This helper centralises that injection so
fail-closed policy tests (e.g. ``test_no_uff_fallback.py``) and topology
builder tests can co-exist without policy regression.

The helper restores the original (empty) state via ``monkeypatch`` teardown,
so registry singletons remain clean for subsequent tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

    from contracts.policies.forcefield import AtomTypeParams


def minimal_organic_atom_types() -> dict[str, AtomTypeParams]:
    """Return a minimal set of artifact-style atom_types for organic CHNO/halogen tests.

    Values are GAFF2-style ballpark numbers; tests use them only to traverse
    the resolution path, not to validate physical accuracy.
    """
    from contracts.policies.forcefield import AtomTypeParams

    return {
        "C": AtomTypeParams(
            mass=12.011, epsilon=0.0860, sigma=3.4, element="C", description="aliphatic carbon"
        ),
        "CA": AtomTypeParams(
            mass=12.011, epsilon=0.0860, sigma=3.4, element="C", description="aromatic carbon"
        ),
        "H": AtomTypeParams(
            mass=1.008, epsilon=0.0157, sigma=2.5, element="H", description="hydrogen"
        ),
        "N": AtomTypeParams(
            mass=14.007, epsilon=0.1700, sigma=3.25, element="N", description="nitrogen"
        ),
        "O": AtomTypeParams(
            mass=15.999, epsilon=0.2100, sigma=3.0, element="O", description="oxygen"
        ),
        "S": AtomTypeParams(
            mass=32.065, epsilon=0.2500, sigma=3.55, element="S", description="sulfur"
        ),
        "Si": AtomTypeParams(
            mass=28.085, epsilon=0.4020, sigma=3.804, element="Si", description="silicon"
        ),
        "Cl": AtomTypeParams(
            mass=35.453, epsilon=0.2650, sigma=3.4, element="Cl", description="chlorine"
        ),
        "F": AtomTypeParams(
            mass=18.998, epsilon=0.0610, sigma=3.118, element="F", description="fluorine"
        ),
    }


def patch_gaff2_atom_types(
    monkeypatch: pytest.MonkeyPatch,
    atom_types: Mapping[str, AtomTypeParams] | None = None,
) -> None:
    """Inject artifact-derived atom_types into the GAFF2 registry config.

    Mutates the live ``bulk_ff_gaff2`` ForceFieldConfig and the
    ``MolTopologyBuilder``-side cached ``_atom_params`` dict resolver.
    The fail-closed policy (empty ``element_fallbacks``) remains intact.

    Args:
        monkeypatch: pytest ``MonkeyPatch`` fixture (auto-restores on teardown).
        atom_types: optional override; defaults to ``minimal_organic_atom_types()``.
    """
    from contracts.policies.forcefield import get_default_ff_registry

    types = dict(atom_types if atom_types is not None else minimal_organic_atom_types())
    registry = get_default_ff_registry()
    config = registry.get("bulk_ff_gaff2")
    if config is None:
        raise RuntimeError("bulk_ff_gaff2 not found in registry — cannot patch")

    monkeypatch.setattr(config, "atom_types", types, raising=False)

    # Patch the resolver dict that MolTopologyBuilder caches at construction.
    # Builder consumes legacy dict[str, dict[str, float]] format, so we
    # serialise the AtomTypeParams instances back to that shape here.
    from forcefield import topology as topology_module

    original_resolver = topology_module._get_ff_params_dict

    def _to_legacy(params: AtomTypeParams) -> dict[str, float]:
        return {
            "mass": params.mass,
            "epsilon": params.epsilon,
            "sigma": params.sigma,
            "charge": params.charge,
        }

    def patched_resolver(ff_config):  # type: ignore[no-untyped-def]
        if ff_config is config:
            merged: dict[str, dict[str, float]] = {
                key: _to_legacy(val) for key, val in types.items()
            }
            for key, val in (getattr(ff_config, "element_fallbacks", {}) or {}).items():
                merged.setdefault(key, _to_legacy(val))
            return merged
        return original_resolver(ff_config)

    monkeypatch.setattr(topology_module, "_get_ff_params_dict", patched_resolver)
