"""Wave 4: mineral_lj_catalog.yaml schema and loader regression."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from forcefield.mineral_lj_loader import (  # noqa: E402
    MINERAL_LJ_CATALOG_PATH,
    SCHEMA_VERSION,
    InterfaceFFEntry,
    MineralLJLoadError,
    UFFEntry,
    load_interface_ff_entries,
    load_interface_ff_params,
    load_uff_fallback_entries,
    load_uff_fallback_params,
)

# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------


class TestCatalogConstants:
    def test_catalog_path_under_data_forcefields(self):
        assert MINERAL_LJ_CATALOG_PATH == "data/forcefields/mineral_lj_catalog.yaml"

    def test_schema_version_is_one(self):
        assert SCHEMA_VERSION == 1


# ---------------------------------------------------------------------------
# Repo yaml loads cleanly
# ---------------------------------------------------------------------------


class TestRepoYamlLoads:
    # Wave 4 boost: lock the EXACT element counts so a silent yaml truncation
    # cannot pass an "at least N" check with a smaller table than expected.
    EXPECTED_INTERFACE_FF_COUNT = 15
    EXPECTED_UFF_COUNT = 103

    def test_interface_ff_entries_load(self):
        entries = load_interface_ff_entries()
        assert isinstance(entries, dict)
        assert len(entries) == self.EXPECTED_INTERFACE_FF_COUNT, (
            f"Wave 4 yaml must ship exactly {self.EXPECTED_INTERFACE_FF_COUNT} "
            "INTERFACE FF elements (matching the legacy hardcoded dict). "
            f"Found {len(entries)} — a yaml edit silently dropped or added "
            "an element."
        )
        for elem, entry in entries.items():
            assert isinstance(entry, InterfaceFFEntry)
            assert entry.element == elem
            assert entry.sigma > 0
            assert entry.epsilon >= 0

    def test_uff_fallback_entries_load(self):
        entries = load_uff_fallback_entries()
        assert isinstance(entries, dict)
        assert len(entries) == self.EXPECTED_UFF_COUNT, (
            f"Wave 4 yaml must ship exactly {self.EXPECTED_UFF_COUNT} UFF "
            "fallback elements (matching the legacy hardcoded dict). "
            f"Found {len(entries)} — a yaml edit silently dropped or added "
            "an element. Re-run the equivalence test to identify the diff."
        )
        for elem, entry in entries.items():
            assert isinstance(entry, UFFEntry)
            assert entry.element == elem
            assert entry.mass > 0
            assert entry.sigma > 0
            assert entry.epsilon >= 0
            assert entry.charge == 0.0  # UFF was fit without electrostatics

    def test_legacy_shape_helpers(self):
        """Wave 4 helpers expose dicts in the legacy shape used by callers."""
        iff = load_interface_ff_params()
        uff = load_uff_fallback_params()
        assert isinstance(iff, dict)
        assert isinstance(uff, dict)
        # Spot-check legacy keys exist
        assert "sigma" in iff["Si"]
        assert "epsilon" in iff["Si"]
        assert "description" in iff["Si"]
        assert "mass" in uff["H"]
        assert "charge" in uff["H"]


# ---------------------------------------------------------------------------
# Anchor values (literature-grounded)
# ---------------------------------------------------------------------------


class TestInterfaceFFAnchors:
    """Lock the canonical Heinz/Emami anchor values so a yaml typo cannot drift them."""

    def test_silica_si_epsilon(self):
        iff = load_interface_ff_params()
        assert iff["Si"]["epsilon"] == pytest.approx(0.00040, abs=1e-6), (
            "INTERFACE FF Si epsilon must remain 0.00040 kcal/mol (Emami 2014, Heinz 2013)"
        )
        assert iff["Si"]["sigma"] == pytest.approx(3.302, abs=1e-4)

    def test_silica_o_epsilon(self):
        iff = load_interface_ff_params()
        assert iff["O"]["epsilon"] == pytest.approx(0.15540, abs=1e-5)
        assert iff["O"]["sigma"] == pytest.approx(3.166, abs=1e-4)

    def test_calcite_anchors_present(self):
        iff = load_interface_ff_params()
        for element in ("Ca", "Mg", "C", "O"):
            assert element in iff
            assert iff[element]["sigma"] > 0

    def test_fcc_metal_high_epsilon_intentional(self):
        """FCC metals (Cu, Ni) intentionally use large LJ epsilon."""
        iff = load_interface_ff_params()
        assert iff["Cu"]["epsilon"] == pytest.approx(4.7200, abs=1e-4)
        assert iff["Ni"]["epsilon"] == pytest.approx(5.6500, abs=1e-4)


# ---------------------------------------------------------------------------
# Loader error handling
# ---------------------------------------------------------------------------


class TestLoaderErrors:
    def test_missing_yaml_raises(self, tmp_path):
        with pytest.raises(MineralLJLoadError, match="not found"):
            load_interface_ff_params(tmp_path / "nonexistent.yaml")

    def test_malformed_json_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("schema_version: 1\n!@#$ not yaml")
        with pytest.raises(MineralLJLoadError):
            load_interface_ff_params(bad)

    def test_unsupported_schema_version_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("schema_version: 999\nversion: '1.0'\ninterface_ff: {}\nuff_fallback: {}\n")
        with pytest.raises(MineralLJLoadError, match="schema_version"):
            load_interface_ff_params(bad)

    def test_missing_section_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("schema_version: 1\nversion: '1.0'\nuff_fallback: {}\n")
        with pytest.raises(MineralLJLoadError, match="interface_ff"):
            load_interface_ff_params(bad)

    def test_malformed_entry_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "schema_version: 1\n"
            "version: '1.0'\n"
            "interface_ff:\n"
            "  Si: not-a-mapping\n"
            "uff_fallback: {}\n"
        )
        with pytest.raises(MineralLJLoadError, match="Si"):
            load_interface_ff_params(bad)
