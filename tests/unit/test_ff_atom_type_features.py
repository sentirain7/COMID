"""Tests for ml.ff_atom_type_features (FF-atom-type interpretable descriptors)."""

from __future__ import annotations

import pytest

from ml.ff_atom_type_features import (
    FF_ATOM_TYPE_FEATURE_NAMES,
    FF_ATOM_TYPE_GROUPS,
    build_ff_atom_type_histogram,
    classify_ff_atom_type,
)


class TestClassify:
    """Pure GAFF2 atom type -> chemical group mapping (no data dependency)."""

    @pytest.mark.parametrize(
        ("ff_type", "expected"),
        [
            ("ca", "aromatic_carbon"),
            ("cp", "aromatic_carbon"),
            ("c3", "aliphatic_carbon"),
            ("c6", "aliphatic_carbon"),
            ("c", "carbonyl_carbon"),
            ("ha", "aromatic_h"),
            ("hc", "aliphatic_h"),
            ("ho", "polar_h"),
            ("hn", "polar_h"),
            ("oh", "hydroxyl_o"),
            ("os", "ether_ester_o"),
            ("o", "carbonyl_o"),
            ("n", "nitrogen"),
            ("nb", "nitrogen"),
            ("ss", "sulfur"),  # reduced (thioether)
            ("sx", "sulfur"),  # reduced (conjugated thioether)
            ("s6", "oxidized_sulfur"),  # sulfone (oxidative aging)
            ("s4", "oxidized_sulfur"),  # sulfoxide
            ("sy", "oxidized_sulfur"),  # conjugated sulfone
            ("cg", "other"),  # sp (alkyne) carbon — NOT aromatic (P1-8)
            ("ch", "other"),
            ("p5", "other"),
            ("f", "other"),
            ("", "other"),
        ],
    )
    def test_buckets(self, ff_type, expected):
        assert classify_ff_atom_type(ff_type) == expected

    def test_case_insensitive(self):
        assert classify_ff_atom_type("CA") == "aromatic_carbon"


class TestHistogram:
    """Composition-weighted normalized histogram (math via monkeypatch)."""

    def _patch_groups(self, monkeypatch, table):
        """Patch per-molecule group counts to a deterministic table."""
        import ml.ff_atom_type_features as mod

        monkeypatch.setattr(
            mod,
            "molecule_ff_atom_group_counts",
            lambda mol_id: {g: table.get(mol_id, {}).get(g, 0) for g in FF_ATOM_TYPE_GROUPS},
        )

    def test_feature_names_stable_and_complete(self):
        assert len(FF_ATOM_TYPE_FEATURE_NAMES) == len(FF_ATOM_TYPE_GROUPS) == 13
        assert FF_ATOM_TYPE_FEATURE_NAMES[0] == "ff_atomtype_frac_aromatic_carbon"

    def test_single_molecule_fractions_sum_to_one(self, monkeypatch):
        self._patch_groups(
            monkeypatch,
            {"M": {"aromatic_carbon": 6, "aromatic_h": 4}},  # 10 atoms
        )
        hist = build_ff_atom_type_histogram({"M": 1})
        assert sum(hist.values()) == pytest.approx(1.0)
        assert hist["ff_atomtype_frac_aromatic_carbon"] == pytest.approx(0.6)
        assert hist["ff_atomtype_frac_aromatic_h"] == pytest.approx(0.4)

    def test_composition_weighting(self, monkeypatch):
        # M1 pure aromatic C (10 atoms), M2 pure aliphatic C (10 atoms).
        self._patch_groups(
            monkeypatch,
            {
                "M1": {"aromatic_carbon": 10},
                "M2": {"aliphatic_carbon": 10},
            },
        )
        # 3x M1 + 1x M2 -> 30 aromatic, 10 aliphatic of 40 total
        hist = build_ff_atom_type_histogram({"M1": 3, "M2": 1})
        assert hist["ff_atomtype_frac_aromatic_carbon"] == pytest.approx(0.75)
        assert hist["ff_atomtype_frac_aliphatic_carbon"] == pytest.approx(0.25)
        assert sum(hist.values()) == pytest.approx(1.0)

    def test_zero_and_negative_counts_skipped(self, monkeypatch):
        self._patch_groups(
            monkeypatch,
            {"M1": {"aromatic_carbon": 10}, "M2": {"sulfur": 10}},
        )
        hist = build_ff_atom_type_histogram({"M1": 2, "M2": 0, "M3": -5})
        assert hist["ff_atomtype_frac_aromatic_carbon"] == pytest.approx(1.0)
        assert hist["ff_atomtype_frac_sulfur"] == pytest.approx(0.0)

    def test_missing_artifacts_yield_all_zero(self, monkeypatch):
        self._patch_groups(monkeypatch, {})  # nothing resolves
        hist = build_ff_atom_type_histogram({"unknown": 5})
        assert set(hist) == set(FF_ATOM_TYPE_FEATURE_NAMES)
        assert all(v == 0.0 for v in hist.values())


class TestRealArtifactIntegration:
    """Integration against a committed GAFF2 artifact, if present."""

    def test_long_aged_asphaltene_has_aging_and_aromatic_signal(self):
        from ml.ff_atom_type_features import molecule_ff_atom_type_counts

        raw = molecule_ff_atom_type_counts("L-AS-Thio")
        if not raw:
            pytest.skip("L-AS-Thio artifact not available in this workspace")

        hist = build_ff_atom_type_histogram({"L-AS-Thio": 1})
        assert sum(hist.values()) == pytest.approx(1.0)
        # Aromatic asphaltene core present
        assert hist["ff_atomtype_frac_aromatic_carbon"] > 0.0
        # Long-aged -> oxidation products (carbonyl O) present
        assert hist["ff_atomtype_frac_carbonyl_o"] > 0.0
