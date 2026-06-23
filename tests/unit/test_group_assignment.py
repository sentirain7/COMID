"""
Unit tests for GroupAssignmentBuilder.

Tests group construction from molecule_ordering metadata,
mol-ID sequential assignment, and verification guard.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from contracts.schemas import GroupEnergySpec
from metrics.group_assignment import GroupAssignmentBuilder


class TestGroupAssignmentBuilder:
    """Tests for GroupAssignmentBuilder."""

    def test_basic_sara_groups(self):
        """4 SARA categories produce correct groups and pairs."""
        builder = GroupAssignmentBuilder()
        ordering = [
            {"mol_id": "SAT_001", "count": 3, "category": "saturate", "atom_count": 50},
            {"mol_id": "ARO_001", "count": 2, "category": "aromatic", "atom_count": 18},
            {"mol_id": "RES_001", "count": 2, "category": "resin", "atom_count": 28},
            {"mol_id": "ASP_001", "count": 1, "category": "asphaltene", "atom_count": 42},
        ]
        spec = builder.build(ordering)

        assert len(spec.groups) == 4
        assert "saturate" in spec.groups
        assert "aromatic" in spec.groups
        assert "resin" in spec.groups
        assert "asphaltene" in spec.groups

        # 4 categories → C(4,2) = 6 pairs
        assert len(spec.pairs) == 6

        # No additive → no additive_pair_label
        assert spec.additive_pair_label is None

    def test_additive_pair_label(self):
        """Additive category sets additive_pair_label."""
        builder = GroupAssignmentBuilder()
        ordering = [
            {"mol_id": "SAT_001", "count": 2, "category": "saturate", "atom_count": 50},
            {"mol_id": "ADD_001", "count": 1, "category": "additive", "atom_count": 30},
        ]
        spec = builder.build(ordering)

        assert len(spec.groups) == 2
        assert spec.additive_pair_label is not None
        assert "additive" in spec.additive_pair_label

    def test_additive_pair_label_none_when_multiple_pairs(self):
        """Multiple additive interactions should not choose an arbitrary single pair."""
        builder = GroupAssignmentBuilder()
        ordering = [
            {"mol_id": "SAT_001", "count": 2, "category": "saturate", "atom_count": 50},
            {"mol_id": "ARO_001", "count": 2, "category": "aromatic", "atom_count": 18},
            {"mol_id": "ADD_001", "count": 1, "category": "additive", "atom_count": 30},
        ]
        spec = builder.build(ordering)

        assert len(spec.groups) == 3
        assert spec.additive_pair_label is None

    def test_atom_counts(self):
        """Group atom counts are correctly aggregated."""
        builder = GroupAssignmentBuilder()
        ordering = [
            {"mol_id": "SAT_001", "count": 4, "category": "saturate", "atom_count": 50},
            {"mol_id": "SAT_002", "count": 3, "category": "saturate", "atom_count": 60},
            {"mol_id": "ARO_001", "count": 2, "category": "aromatic", "atom_count": 18},
        ]
        spec = builder.build(ordering)

        # saturate: 4*50 + 3*60 = 380
        assert spec.atom_counts["saturate"] == 380
        # aromatic: 2*18 = 36
        assert spec.atom_counts["aromatic"] == 36

    def test_sequential_mol_ids(self):
        """Molecule IDs are assigned sequentially starting from 1."""
        builder = GroupAssignmentBuilder()
        ordering = [
            {"mol_id": "SAT_001", "count": 3, "category": "saturate", "atom_count": 50},
            {"mol_id": "ARO_001", "count": 2, "category": "aromatic", "atom_count": 18},
        ]
        spec = builder.build(ordering)

        # saturate gets mol IDs 1, 2, 3
        assert spec.groups["saturate"] == [1, 2, 3]
        # aromatic gets mol IDs 4, 5
        assert spec.groups["aromatic"] == [4, 5]

    def test_empty_ordering(self):
        """Empty molecule_ordering returns empty spec."""
        builder = GroupAssignmentBuilder()
        spec = builder.build([])

        assert spec.groups == {}
        assert spec.pairs == []
        assert spec.atom_counts == {}
        assert spec.additive_pair_label is None

    def test_zero_count_skipped(self):
        """Molecules with count=0 are skipped."""
        builder = GroupAssignmentBuilder()
        ordering = [
            {"mol_id": "SAT_001", "count": 0, "category": "saturate", "atom_count": 50},
            {"mol_id": "ARO_001", "count": 2, "category": "aromatic", "atom_count": 18},
        ]
        spec = builder.build(ordering)

        # Only aromatic group, no pairs (need 2+ groups)
        assert len(spec.groups) == 1
        assert "aromatic" in spec.groups
        assert len(spec.pairs) == 0

    def test_verify_mol_ids_pass(self):
        """mol-ID verification passes when all IDs exist in dump."""
        builder = GroupAssignmentBuilder()
        spec = GroupEnergySpec(
            groups={"saturate": [1, 2, 3], "aromatic": [4, 5]},
        )
        dump_mol_ids = {1, 2, 3, 4, 5}
        assert builder.verify_mol_ids(spec, dump_mol_ids) is True

    def test_verify_mol_ids_pass_with_extra(self):
        """Verification passes even if dump has extra mol IDs."""
        builder = GroupAssignmentBuilder()
        spec = GroupEnergySpec(
            groups={"saturate": [1, 2], "aromatic": [3]},
        )
        dump_mol_ids = {1, 2, 3, 4, 5, 6}  # Extra IDs OK
        assert builder.verify_mol_ids(spec, dump_mol_ids) is True

    def test_verify_mol_ids_fail(self):
        """mol-ID verification fails when IDs are missing from dump."""
        builder = GroupAssignmentBuilder()
        spec = GroupEnergySpec(
            groups={"saturate": [1, 2, 3], "aromatic": [4, 5]},
        )
        dump_mol_ids = {1, 2, 3}  # Missing 4, 5
        assert builder.verify_mol_ids(spec, dump_mol_ids) is False

    def test_verify_mol_ids_empty_spec(self):
        """Verification fails with empty spec."""
        builder = GroupAssignmentBuilder()
        spec = GroupEnergySpec()
        assert builder.verify_mol_ids(spec, {1, 2, 3}) is False

    def test_verify_mol_ids_empty_dump(self):
        """Verification fails with empty dump mol IDs."""
        builder = GroupAssignmentBuilder()
        spec = GroupEnergySpec(groups={"saturate": [1, 2]})
        assert builder.verify_mol_ids(spec, set()) is False

    def test_multiple_molecules_same_category(self):
        """Multiple molecule types in same SARA category merge correctly."""
        builder = GroupAssignmentBuilder()
        ordering = [
            {"mol_id": "SAT_001", "count": 2, "category": "saturate", "atom_count": 50},
            {"mol_id": "ARO_001", "count": 1, "category": "aromatic", "atom_count": 18},
            {"mol_id": "SAT_002", "count": 3, "category": "saturate", "atom_count": 60},
        ]
        spec = builder.build(ordering)

        # SAT_001 gets 1,2; ARO_001 gets 3; SAT_002 gets 4,5,6
        assert spec.groups["saturate"] == [1, 2, 4, 5, 6]
        assert spec.groups["aromatic"] == [3]
        assert spec.atom_counts["saturate"] == 2 * 50 + 3 * 60  # 280

    def test_bulk_group_pairs_excludes_self_pairs(self):
        """bulk GroupAssignmentBuilder의 현재 한계: self-pair를 생성하지 않음.

        이 동작은 현재 구현을 고정하는 회귀 테스트다. 같은 카테고리 내
        분자간 상호작용도 cohesion에 기여할 수 있으므로, 이 결과를
        총 intermolecular energy의 완전한 표현으로 해석하면 안 된다.
        """
        builder = GroupAssignmentBuilder()
        ordering = [
            {"mol_id": "sat1", "count": 2, "category": "saturate", "atom_count": 50},
            {"mol_id": "aro1", "count": 2, "category": "aromatic", "atom_count": 60},
        ]
        spec = builder.build(ordering)

        # sorted() 사용으로 aromatic_saturate가 생성됨 (deterministic)
        labels = {p.label for p in spec.pairs}
        assert labels == {"aromatic_saturate"}

        # self-pair 미생성 확인
        assert "saturate_saturate" not in labels
        assert "aromatic_aromatic" not in labels

    def test_four_categories_no_self_pairs(self):
        """4 SARA 카테고리에서도 현재 구현은 self-pair를 만들지 않는다."""
        builder = GroupAssignmentBuilder()
        ordering = [
            {"mol_id": "sat1", "count": 2, "category": "saturate", "atom_count": 50},
            {"mol_id": "aro1", "count": 2, "category": "aromatic", "atom_count": 60},
            {"mol_id": "res1", "count": 2, "category": "resin", "atom_count": 70},
            {"mol_id": "asp1", "count": 1, "category": "asphaltene", "atom_count": 80},
        ]
        spec = builder.build(ordering)

        labels = {p.label for p in spec.pairs}

        # C(4,2) = 6 cross-category pairs
        assert len(labels) == 6

        # self-pair 없음 확인
        self_pairs = {
            "saturate_saturate",
            "aromatic_aromatic",
            "resin_resin",
            "asphaltene_asphaltene",
        }
        assert labels.isdisjoint(self_pairs)
