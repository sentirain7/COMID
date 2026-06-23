"""Tests for GHG emission factor policy and calculation."""

import pytest

from contracts.policies.ghg import GHGPolicy


@pytest.fixture()
def policy() -> GHGPolicy:
    """Minimal policy matching ghg_inventory.yaml."""
    return GHGPolicy(
        binder_molecules={
            "SA-Squalane": 0.40,
            "SA-Hopane": 0.44,
            "AR-PHPN": 0.48,
            "AR-DOCHN": 0.47,
            "RE-Quin": 0.52,
            "RE-Thio": 0.54,
            "AS-Pyrrole": 0.58,
            "AS-Phenol": 0.55,
            "AS-Thio": 0.56,
        },
        sara_fallback={
            "saturate": 0.42,
            "aromatic": 0.48,
            "resin": 0.51,
            "asphaltene": 0.55,
        },
        additives={
            "SBS": 3.40,
            "PPA": 2.10,
            "CRM": -0.50,
            "Lignin": -0.30,
            "Elvaloy": 2.80,
        },
        default_binder_ef=0.50,
        default_additive_ef=0.0,
    )


class TestGetFactor:
    def test_binder_base_id(self, policy: GHGPolicy) -> None:
        assert policy.get_factor("SA-Squalane") == 0.40

    def test_aged_binder(self, policy: GHGPolicy) -> None:
        # U-AS-Thio-0293 → base_id AS-Thio → 0.56
        assert policy.get_factor("U-AS-Thio-0293") == 0.56

    def test_aged_binder_short(self, policy: GHGPolicy) -> None:
        # S-AR-PHPN-0293 → base_id AR-PHPN → 0.48
        assert policy.get_factor("S-AR-PHPN-0293") == 0.48

    def test_additive_canonical(self, policy: GHGPolicy) -> None:
        assert policy.get_factor("SBS") == 3.40

    def test_additive_alias(self, policy: GHGPolicy) -> None:
        # ADD_SBS_001 → canonical SBS → 3.40
        assert policy.get_factor("ADD_SBS_001") == 3.40

    def test_unknown_fallback(self, policy: GHGPolicy) -> None:
        assert policy.get_factor("UNKNOWN_MOLECULE_XYZ") == 0.50

    def test_sara_fallback(self, policy: GHGPolicy) -> None:
        # RE-Unknown → base_id parsed → not in binder_molecules → sara fallback "resin" = 0.51
        assert policy.get_factor("RE-Unknown") == 0.51

    def test_crm_negative(self, policy: GHGPolicy) -> None:
        assert policy.get_factor("CRM") == -0.50

    def test_aging_wrapped_additive(self, policy: GHGPolicy) -> None:
        """U-SBS-0293 (composition_builder output) must resolve to SBS EF."""
        assert policy.get_factor("U-SBS-0293") == 3.40

    def test_aging_wrapped_additive_short(self, policy: GHGPolicy) -> None:
        """S-CRM-0313 must resolve to CRM EF."""
        assert policy.get_factor("S-CRM-0313") == -0.50

    def test_aging_wrapped_additive_ppa(self, policy: GHGPolicy) -> None:
        """U-PPA-0293 must resolve to PPA EF."""
        assert policy.get_factor("U-PPA-0293") == 2.10

    def test_aging_wrapped_elvaloy(self, policy: GHGPolicy) -> None:
        """L-Elvaloy-0293 must resolve to Elvaloy EF."""
        assert policy.get_factor("L-Elvaloy-0293") == 2.80


class TestCalculateWeightFractions:
    def test_basic(self, policy: GHGPolicy) -> None:
        fractions = [
            ("SA-Squalane", 0.50),
            ("AS-Thio", 0.50),
        ]
        result = policy.calculate_ghg_from_weight_fractions(fractions)
        expected = 0.50 * 0.40 + 0.50 * 0.56
        assert abs(result - expected) < 1e-6

    def test_multiple_additives(self, policy: GHGPolicy) -> None:
        fractions = [
            ("SA-Squalane", 0.80),
            ("SBS", 0.15),
            ("PPA", 0.05),
        ]
        result = policy.calculate_ghg_from_weight_fractions(fractions)
        expected = 0.80 * 0.40 + 0.15 * 3.40 + 0.05 * 2.10
        assert abs(result - expected) < 1e-6

    def test_crm_reduces_total(self, policy: GHGPolicy) -> None:
        fractions = [
            ("SA-Squalane", 0.90),
            ("CRM", 0.10),
        ]
        result = policy.calculate_ghg_from_weight_fractions(fractions)
        expected = 0.90 * 0.40 + 0.10 * (-0.50)
        assert abs(result - expected) < 1e-6
        # Should be lower than pure binder
        assert result < 0.40

    def test_empty(self, policy: GHGPolicy) -> None:
        assert policy.calculate_ghg_from_weight_fractions([]) == 0.0


class TestCalculateSARA:
    def test_pure_binder(self, policy: GHGPolicy) -> None:
        result = policy.calculate_ghg_from_sara(
            comp_saturate_wt=20.0,
            comp_aromatic_wt=35.0,
            comp_resin_wt=30.0,
            comp_asphaltene_wt=15.0,
            additive_mol_id=None,
            additive_wt=0.0,
        )
        # All binder (binder_frac=1.0), weighted by SARA
        total = 20 + 35 + 30 + 15
        expected = (
            (20 / total) * 0.42 + (35 / total) * 0.48 + (30 / total) * 0.51 + (15 / total) * 0.55
        )
        assert abs(result - expected) < 1e-6

    def test_with_additive_wt_percent(self, policy: GHGPolicy) -> None:
        result = policy.calculate_ghg_from_sara(
            comp_saturate_wt=20.0,
            comp_aromatic_wt=35.0,
            comp_resin_wt=30.0,
            comp_asphaltene_wt=15.0,
            additive_mol_id="SBS",
            additive_wt=5.0,  # 5 wt%
        )
        binder_frac = 0.95
        add_frac = 0.05
        total = 20 + 35 + 30 + 15
        binder_ghg = binder_frac * (
            (20 / total) * 0.42 + (35 / total) * 0.48 + (30 / total) * 0.51 + (15 / total) * 0.55
        )
        additive_ghg = add_frac * 3.40
        expected = binder_ghg + additive_ghg
        assert abs(result - expected) < 1e-6

    def test_zero_sara_total(self, policy: GHGPolicy) -> None:
        result = policy.calculate_ghg_from_sara(
            comp_saturate_wt=0.0,
            comp_aromatic_wt=0.0,
            comp_resin_wt=0.0,
            comp_asphaltene_wt=0.0,
            additive_mol_id=None,
            additive_wt=0.0,
        )
        assert result == 0.0


class TestEdgeCases:
    def test_regex_does_not_match_binder_as_additive(self, policy: GHGPolicy) -> None:
        """U-AS-Thio-0293 must NOT match aging-wrap regex (contains dash in inner).

        Should fall through to parse_molecule_id → binder_molecules['AS-Thio'] = 0.56.
        """
        assert policy.get_factor("U-AS-Thio-0293") == 0.56

    def test_additive_wt_clamped_over_100(self, policy: GHGPolicy) -> None:
        """additive_wt=150 should be clamped to 100%, not produce negative binder_frac."""
        result = policy.calculate_ghg_from_sara(
            comp_saturate_wt=20.0,
            comp_aromatic_wt=35.0,
            comp_resin_wt=30.0,
            comp_asphaltene_wt=15.0,
            additive_mol_id="SBS",
            additive_wt=150.0,
        )
        # Clamped: add_frac=1.0, binder_frac=0.0 → pure additive GHG
        assert abs(result - 3.40) < 1e-6

    def test_additive_wt_clamped_negative(self, policy: GHGPolicy) -> None:
        """additive_wt=-5 should be clamped to 0%, not produce >1.0 binder_frac."""
        result = policy.calculate_ghg_from_sara(
            comp_saturate_wt=20.0,
            comp_aromatic_wt=35.0,
            comp_resin_wt=30.0,
            comp_asphaltene_wt=15.0,
            additive_mol_id="SBS",
            additive_wt=-5.0,
        )
        # Clamped: add_frac=0.0, binder_frac=1.0 → pure binder GHG (same as no additive)
        total = 20 + 35 + 30 + 15
        expected = (
            (20 / total) * 0.42 + (35 / total) * 0.48 + (30 / total) * 0.51 + (15 / total) * 0.55
        )
        assert abs(result - expected) < 1e-6


class TestYAMLLoading:
    def test_load_ghg_inventory(self) -> None:
        from common.library_config import load_ghg_inventory

        cfg = load_ghg_inventory()
        # Should load successfully from data/molecules/ghg_inventory.yaml
        assert "binder_molecules" in cfg
        assert "sara_fallback" in cfg
        assert "additives" in cfg
        assert "defaults" in cfg
        assert cfg["binder_molecules"]["SA-Squalane"] == 0.40
        assert cfg["additives"]["SBS"] == 3.40

    def test_policy_from_yaml(self) -> None:
        from common.library_config import load_ghg_inventory

        cfg = load_ghg_inventory()
        p = GHGPolicy(
            binder_molecules=cfg.get("binder_molecules", {}),
            sara_fallback=cfg.get("sara_fallback", {}),
            additives=cfg.get("additives", {}),
            default_binder_ef=cfg.get("defaults", {}).get("binder", 0.50),
            default_additive_ef=cfg.get("defaults", {}).get("additive", 0.0),
            version=cfg.get("version", "1.0"),
        )
        assert p.get_factor("SA-Squalane") == 0.40
        assert p.get_factor("CRM") == -0.50


class TestGHGAsPropertyTarget:
    """GHG emission should be usable as a property design target."""

    def test_ghg_registered_in_metrics_registry(self) -> None:
        from contracts.policies.metrics import DEFAULT_METRICS_REGISTRY

        assert DEFAULT_METRICS_REGISTRY.is_valid_metric("ghg_emission")
        assert DEFAULT_METRICS_REGISTRY.get_unit("ghg_emission") == "kgCO2e/kg"

    def test_ghg_from_weight_fractions_positive(self, policy: GHGPolicy) -> None:
        """A composition containing SBS should yield a positive GHG emission value."""
        ghg = policy.calculate_ghg_from_weight_fractions(
            [("SA-Squalane", 0.5), ("SBS", 0.05), ("AS-Thio", 0.45)]
        )
        assert ghg > 0  # Composition includes SBS (3.40)
