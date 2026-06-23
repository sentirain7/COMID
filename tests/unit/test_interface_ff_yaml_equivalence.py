"""Wave 4: numerical equivalence between yaml SSOT and hardcoded fallback.

The Wave 4 contract is that the editable SSOT
``data/forcefields/mineral_lj_catalog.yaml`` and the runtime safety
net dicts in ``forcefield/interface_ff.py`` and
``forcefield/uff_element_fallback.py`` must hold IDENTICAL values
element by element. If they drift, the runtime can silently use a
different LJ table depending on whether the yaml is present (which
varies between production and tmp_path test environments) and the
silica/binder interface physics will be wrong on at least one path.

This file is the lock. Every element in either source must:

* exist in the OTHER source
* have IDENTICAL sigma / epsilon / mass / charge / description values
  (within float tolerance for the numerical fields)

When updating an INTERFACE FF or UFF value, edit BOTH places. The
test failure message will tell you which side is missing the change.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from forcefield.interface_ff import (  # noqa: E402
    _INTERFACE_FF_HARDCODED_FALLBACK,
    INTERFACE_FF_MINERAL_PARAMS,
)
from forcefield.mineral_lj_loader import (  # noqa: E402
    load_interface_ff_params,
    load_uff_fallback_params,
)
from forcefield.uff_element_fallback import (  # noqa: E402
    _UFF_HARDCODED_FALLBACK,
    UFF_ELEMENT_FALLBACKS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_param_equivalent(
    label: str,
    element: str,
    yaml_value: dict,
    legacy_value: dict,
    *,
    numeric_keys: tuple[str, ...],
    string_keys: tuple[str, ...],
) -> None:
    """Element-by-element field-by-field equivalence assertion."""
    for key in numeric_keys:
        yaml_v = float(yaml_value[key])
        legacy_v = float(legacy_value[key])
        assert yaml_v == pytest.approx(legacy_v, abs=1e-9), (
            f"{label} {element} {key}: yaml={yaml_v} != legacy={legacy_v}. "
            "Wave 4 numerical equivalence violated. Edit BOTH the yaml at "
            "data/forcefields/mineral_lj_catalog.yaml AND the hardcoded "
            "fallback in src/forcefield/{interface_ff,uff_element_fallback}.py."
        )
    for key in string_keys:
        yaml_v = str(yaml_value[key])
        legacy_v = str(legacy_value[key])
        assert yaml_v == legacy_v, (
            f"{label} {element} {key}: yaml description != legacy description"
        )


# ---------------------------------------------------------------------------
# INTERFACE FF equivalence
# ---------------------------------------------------------------------------


class TestInterfaceFFYamlEquivalence:
    """Yaml SSOT must equal the hardcoded fallback element by element."""

    def test_element_sets_match(self):
        yaml_params = load_interface_ff_params()
        legacy_keys = set(_INTERFACE_FF_HARDCODED_FALLBACK.keys())
        yaml_keys = set(yaml_params.keys())

        only_yaml = yaml_keys - legacy_keys
        only_legacy = legacy_keys - yaml_keys
        assert not only_yaml, f"Yaml has elements not in legacy hardcoded dict: {sorted(only_yaml)}"
        assert not only_legacy, (
            f"Legacy hardcoded dict has elements not in yaml: {sorted(only_legacy)}"
        )

    def test_every_element_value_matches(self):
        yaml_params = load_interface_ff_params()
        for element, legacy in _INTERFACE_FF_HARDCODED_FALLBACK.items():
            assert element in yaml_params, f"Yaml missing element {element}"
            _assert_param_equivalent(
                "interface_ff",
                element,
                yaml_params[element],
                legacy,
                numeric_keys=("sigma", "epsilon"),
                string_keys=("description",),
            )

    def test_runtime_dict_uses_yaml_when_available(self):
        """The module-level INTERFACE_FF_MINERAL_PARAMS in production
        environments comes from the yaml. Verify the runtime dict has
        exactly the yaml's values for the canonical anchor elements."""
        yaml_params = load_interface_ff_params()
        for element in ("Si", "O", "Ca", "Cu", "H"):
            assert INTERFACE_FF_MINERAL_PARAMS[element]["epsilon"] == pytest.approx(
                yaml_params[element]["epsilon"], abs=1e-9
            )
            assert INTERFACE_FF_MINERAL_PARAMS[element]["sigma"] == pytest.approx(
                yaml_params[element]["sigma"], abs=1e-9
            )

    def test_runtime_dict_equals_legacy_for_anchors(self):
        """Belt-and-suspenders: runtime dict ≡ legacy fallback ≡ yaml.

        If the yaml is missing in some test environment, the runtime
        dict falls back to the hardcoded values, and these still must
        equal the legacy fallback (trivially true; this just locks the
        invariant for human readers)."""
        for element in ("Si", "O", "Ca", "Cu", "H"):
            assert INTERFACE_FF_MINERAL_PARAMS[element]["epsilon"] == pytest.approx(
                _INTERFACE_FF_HARDCODED_FALLBACK[element]["epsilon"], abs=1e-9
            )


# ---------------------------------------------------------------------------
# UFF fallback equivalence
# ---------------------------------------------------------------------------


class TestUFFYamlEquivalence:
    def test_element_sets_match(self):
        yaml_params = load_uff_fallback_params()
        legacy_keys = set(_UFF_HARDCODED_FALLBACK.keys())
        yaml_keys = set(yaml_params.keys())

        only_yaml = yaml_keys - legacy_keys
        only_legacy = legacy_keys - yaml_keys
        assert not only_yaml, (
            f"Yaml has UFF elements not in legacy hardcoded dict: {sorted(only_yaml)}"
        )
        assert not only_legacy, (
            f"Legacy hardcoded UFF dict has elements not in yaml: {sorted(only_legacy)}"
        )

    def test_every_element_value_matches(self):
        yaml_params = load_uff_fallback_params()
        for element, legacy in _UFF_HARDCODED_FALLBACK.items():
            assert element in yaml_params, f"Yaml missing UFF element {element}"
            _assert_param_equivalent(
                "uff_fallback",
                element,
                yaml_params[element],
                legacy,
                numeric_keys=("mass", "sigma", "epsilon", "charge"),
                string_keys=("description",),
            )

    def test_runtime_dict_uses_yaml_when_available(self):
        yaml_params = load_uff_fallback_params()
        # Spot check a few elements that span the periodic table
        for element in ("H", "C", "Si", "Cu", "U"):
            for key in ("mass", "sigma", "epsilon", "charge"):
                assert UFF_ELEMENT_FALLBACKS[element][key] == pytest.approx(
                    yaml_params[element][key], abs=1e-9
                )


# ---------------------------------------------------------------------------
# SSOT split (Wave 4 design contract)
# ---------------------------------------------------------------------------


class TestYamlBooleanTraps:
    """Wave 4 boost: lock the YAML 1.1 boolean-keyword traps in element keys.

    PyYAML safe_load still parses bare ``No`` / ``Yes`` / ``On`` / ``Off``
    / ``True`` / ``False`` as Python booleans. Periodic-table elements
    that collide with this list (currently only ``No`` for Nobelium)
    MUST be quoted in the yaml. If a future re-edit drops the quotes,
    these tests fail loudly.
    """

    def test_nobelium_is_a_string_key(self):
        """The element 'No' (Nobelium) must round-trip as the string 'No'."""
        params = load_uff_fallback_params()
        assert "No" in params
        # The Python dict key must be the string "No", not the bool False
        keys = [k for k in params if k == "No"]
        assert keys, "Nobelium 'No' key missing from yaml — likely YAML boolean trap"
        # Spot-check the legacy value survived the round trip
        assert params["No"]["mass"] == pytest.approx(259.0, abs=1e-3)

    def test_no_boolean_keys_in_uff_section(self):
        """Defense in depth: no Python bool ever appears as a UFF element key."""
        params = load_uff_fallback_params()
        for key in params:
            assert isinstance(key, str), (
                f"UFF yaml has non-string key {key!r} (type={type(key).__name__}); "
                "this is the YAML boolean-keyword trap. Quote the offending "
                "element symbol in mineral_lj_catalog.yaml."
            )

    def test_no_boolean_keys_in_interface_ff_section(self):
        params = load_interface_ff_params()
        for key in params:
            assert isinstance(key, str), (
                f"INTERFACE FF yaml has non-string key {key!r}; "
                "quote the element symbol in mineral_lj_catalog.yaml"
            )


class TestSSOTSplit:
    """Wave 4 plan v3: mineral_lj_catalog and inorganic_profiles are
    intentionally SEPARATE SSOTs. This test locks the design — folding
    them into a single yaml or a single executor would couple the
    cross-interaction LJ catalog (cheap, additive) to the site-rule
    physics package (expensive, mineral-specific).
    """

    def test_inorganic_profiles_yaml_still_separate(self):
        from common.pathing import get_project_root

        root = get_project_root()
        assert (root / "data" / "forcefields" / "inorganic_profiles.yaml").exists(), (
            "Wave 4 must NOT delete inorganic_profiles.yaml — site-rule "
            "SSOT remains separate from mineral_lj_catalog.yaml"
        )
        assert (root / "data" / "forcefields" / "mineral_lj_catalog.yaml").exists(), (
            "Wave 4 mineral_lj_catalog.yaml must exist as a separate SSOT"
        )

    def test_mineral_lj_catalog_has_no_site_rules(self):
        """The Wave 4 yaml is element-level only — no site_rules anywhere.

        Site rules belong to inorganic_profiles.yaml. Folding them in
        here would couple two SSOTs and reintroduce the drift that
        Wave 4 is trying to prevent.
        """
        import yaml as _yaml

        from common.pathing import get_project_root

        path = get_project_root() / "data" / "forcefields" / "mineral_lj_catalog.yaml"
        payload = _yaml.safe_load(path.read_text())
        assert "site_rules" not in payload
        for section_name in ("interface_ff", "uff_fallback"):
            section = payload.get(section_name, {})
            for element, entry in section.items():
                assert "site_rules" not in entry, (
                    f"{section_name}.{element} must not contain site_rules; "
                    "those belong to inorganic_profiles.yaml"
                )
                assert "neighbor_pattern" not in entry, (
                    f"{section_name}.{element} must not contain neighbor_pattern"
                )
