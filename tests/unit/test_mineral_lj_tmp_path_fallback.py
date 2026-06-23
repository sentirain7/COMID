"""Wave 4 boost: tmp_path module-reload fallback regression.

The Wave 4 contract is that ``forcefield.interface_ff`` and
``forcefield.uff_element_fallback`` must work in BOTH environments:

* production (yaml present) → module-level
  ``INTERFACE_FF_MINERAL_PARAMS`` / ``UFF_ELEMENT_FALLBACKS`` is
  populated from the yaml SSOT
* tmp_path tests / fresh checkouts (yaml missing) → the module
  re-imports cleanly using the hardcoded fallback dict
  ``_INTERFACE_FF_HARDCODED_FALLBACK`` / ``_UFF_HARDCODED_FALLBACK``

The Wave 4 numerical-equivalence regression in
``test_interface_ff_yaml_equivalence.py`` covers the production
yaml-present case but it cannot exercise the tmp_path fallback at the
module level — once those modules are imported, the module-level dicts
are frozen for the rest of the test session. This file isolates the
fallback path by:

1. Setting ``ASPHALT_PROJECT_ROOT`` to a tmp directory that has no
   ``data/forcefields/mineral_lj_catalog.yaml``.
2. Forcefully evicting the relevant modules from ``sys.modules``.
3. Re-importing them and confirming the module-level dicts are
   populated AND match the legacy hardcoded fallback element by element.

After each test the env var is reverted and the modules are reloaded
again so subsequent tests in this process see the production state.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# Names of the modules we'll be re-importing.
_INTERFACE_FF_MOD = "forcefield.interface_ff"
_UFF_FALLBACK_MOD = "forcefield.uff_element_fallback"
_LOADER_MOD = "forcefield.mineral_lj_loader"
_PATHING_MOD = "common.pathing"


def _evict_modules() -> None:
    """Drop the Wave 4 modules from sys.modules so a fresh import re-runs
    the module-level _load_from_yaml_or_fallback() code path."""
    for name in (_INTERFACE_FF_MOD, _UFF_FALLBACK_MOD, _LOADER_MOD, _PATHING_MOD):
        sys.modules.pop(name, None)


@pytest.fixture
def tmp_project_root(tmp_path, monkeypatch):
    """Point ASPHALT_PROJECT_ROOT at an empty tmp dir AND evict the Wave 4
    modules so the next import triggers the fallback path."""
    monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
    _evict_modules()
    yield tmp_path
    # Tear down: drop the tmp-loaded modules so subsequent tests in this
    # process re-import them against the real repo root.
    monkeypatch.delenv("ASPHALT_PROJECT_ROOT", raising=False)
    _evict_modules()


def test_interface_ff_module_reimports_with_hardcoded_fallback(tmp_project_root):
    """Module-level INTERFACE_FF_MINERAL_PARAMS must populate from the
    hardcoded fallback when the yaml is absent."""
    # Sanity: the tmp project root really does NOT have the yaml file.
    expected_yaml = tmp_project_root / "data" / "forcefields" / "mineral_lj_catalog.yaml"
    assert not expected_yaml.exists()

    interface_ff = importlib.import_module(_INTERFACE_FF_MOD)

    # Wave 4 contract: the runtime dict must equal the hardcoded fallback
    # element by element when the yaml is missing.
    runtime = interface_ff.INTERFACE_FF_MINERAL_PARAMS
    fallback = interface_ff._INTERFACE_FF_HARDCODED_FALLBACK

    assert runtime is not None
    assert len(runtime) == 15, (
        f"INTERFACE FF tmp-fallback path produced {len(runtime)} entries; expected the hardcoded 15"
    )
    assert set(runtime.keys()) == set(fallback.keys())

    # Per-element value lockdown
    for element, expected in fallback.items():
        actual = runtime[element]
        assert actual["sigma"] == pytest.approx(float(expected["sigma"]), abs=1e-9)
        assert actual["epsilon"] == pytest.approx(float(expected["epsilon"]), abs=1e-9)

    # Anchor lockdown: Si MUST still be 0.0004 (Emami 2014 / Heinz 2013)
    assert runtime["Si"]["epsilon"] == pytest.approx(0.0004, abs=1e-9)
    assert runtime["O"]["epsilon"] == pytest.approx(0.15540, abs=1e-9)


def test_uff_fallback_module_reimports_with_hardcoded_fallback(tmp_project_root):
    """Same lockdown for UFF_ELEMENT_FALLBACKS."""
    expected_yaml = tmp_project_root / "data" / "forcefields" / "mineral_lj_catalog.yaml"
    assert not expected_yaml.exists()

    uff_module = importlib.import_module(_UFF_FALLBACK_MOD)

    runtime = uff_module.UFF_ELEMENT_FALLBACKS
    fallback = uff_module._UFF_HARDCODED_FALLBACK

    assert runtime is not None
    assert len(runtime) == 103, (
        f"UFF tmp-fallback path produced {len(runtime)} entries; expected the hardcoded 103"
    )
    assert set(runtime.keys()) == set(fallback.keys())

    # Spot-check a few elements that span the periodic table
    for element in ("H", "C", "Si", "Cu", "U"):
        for key in ("mass", "sigma", "epsilon", "charge"):
            assert runtime[element][key] == pytest.approx(
                float(fallback[element][key]), abs=1e-9
            ), (
                f"UFF tmp-fallback {element}.{key} drift: "
                f"runtime={runtime[element][key]} vs fallback={fallback[element][key]}"
            )


def test_loader_raises_when_yaml_missing(tmp_project_root):
    """The loader itself must raise MineralLJLoadError in the tmp env so
    callers (other than interface_ff/uff_element_fallback) cannot
    silently fall through to a default."""
    loader = importlib.import_module(_LOADER_MOD)

    with pytest.raises(loader.MineralLJLoadError, match="not found"):
        loader.load_interface_ff_params()
    with pytest.raises(loader.MineralLJLoadError, match="not found"):
        loader.load_uff_fallback_params()


def test_re_import_after_teardown_returns_to_yaml_path():
    """After the tmp_project_root fixture's teardown, the modules must
    re-import against the real repo root and load from the yaml SSOT."""
    # The previous tests' teardown evicted the modules, so this import
    # is from scratch against the production env.
    interface_ff = importlib.import_module(_INTERFACE_FF_MOD)
    uff_module = importlib.import_module(_UFF_FALLBACK_MOD)

    # Production runtime dicts must still have the expected counts. If
    # the teardown leaked tmp-state, this would surface immediately.
    assert len(interface_ff.INTERFACE_FF_MINERAL_PARAMS) == 15
    assert len(uff_module.UFF_ELEMENT_FALLBACKS) == 103
    assert interface_ff.INTERFACE_FF_MINERAL_PARAMS["Si"]["epsilon"] == pytest.approx(
        0.0004, abs=1e-9
    )
