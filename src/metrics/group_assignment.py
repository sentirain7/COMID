"""
Group assignment builder for LAMMPS group/group energy decomposition.

Constructs GroupEnergySpec from BuildResult.molecule_ordering metadata,
mapping SARA categories to LAMMPS molecule IDs for group/group compute.
"""

from __future__ import annotations

from itertools import combinations

from common.logging import get_logger
from contracts.schemas import GroupEnergySpec, GroupPairSpec, GroupSelector

logger = get_logger("metrics.group_assignment")


class GroupAssignmentBuilder:
    """Build GroupEnergySpec from molecule_ordering metadata.

    Packmol assigns sequential molecule IDs (1-based) in the order
    molecules are listed. This builder uses that ordering to map
    each SARA category to its LAMMPS molecule IDs.
    """

    def build(self, molecule_ordering: list[dict]) -> GroupEnergySpec:
        """Construct GroupEnergySpec from molecule ordering metadata.

        Args:
            molecule_ordering: List of dicts with keys:
                mol_id (str), count (int), category (str), atom_count (int).
                Ordered by Packmol packing sequence.

        Returns:
            GroupEnergySpec with groups, pairs, atom_counts, and
            additive_pair_label (if additive category present).
        """
        if not molecule_ordering:
            return GroupEnergySpec()

        # 1. Assign sequential molecule IDs and group by category
        groups: dict[str, list[int]] = {}
        atom_counts: dict[str, int] = {}
        current_mol_id = 1  # LAMMPS molecule IDs start at 1

        for entry in molecule_ordering:
            count = int(entry.get("count", 0))
            category = str(entry.get("category", "unknown"))
            atom_count = int(entry.get("atom_count", 0))

            if count <= 0:
                continue

            if category not in groups:
                groups[category] = []
                atom_counts[category] = 0

            for _ in range(count):
                groups[category].append(current_mol_id)
                current_mol_id += 1

            atom_counts[category] += atom_count * count

        if not groups:
            return GroupEnergySpec()

        # 2. Generate unique category pairs
        sorted_categories = sorted(groups.keys())
        pairs: list[GroupPairSpec] = []
        for cat_a, cat_b in combinations(sorted_categories, 2):
            label = f"{cat_a}_{cat_b}"
            pairs.append(GroupPairSpec(label=label, group_a=cat_a, group_b=cat_b))

        # 3. Determine additive pair label
        additive_pair_label: str | None = None
        if "additive" in groups:
            additive_pairs = [
                pair.label
                for pair in pairs
                if pair.group_a == "additive" or pair.group_b == "additive"
            ]
            if len(additive_pairs) == 1:
                additive_pair_label = additive_pairs[0]
            elif len(additive_pairs) > 1:
                logger.info(
                    "Multiple additive interaction pairs detected; "
                    "skip e_inter_additive_binder single-label metric."
                )

        logger.info(
            f"Built group assignment: {len(groups)} groups, "
            f"{len(pairs)} pairs, additive_pair={additive_pair_label}"
        )

        return GroupEnergySpec(
            groups=groups,
            pairs=pairs,
            atom_counts=atom_counts,
            additive_pair_label=additive_pair_label,
        )

    def verify_mol_ids(
        self,
        spec: GroupEnergySpec,
        dump_frame_mol_ids: set[int],
    ) -> bool:
        """Verify mol-ID sequential assignment against dump data.

        Checks that all molecule IDs in spec.groups actually exist
        in the dump frame. Mismatch indicates the sequential assignment
        assumption is invalid.

        Args:
            spec: GroupEnergySpec with assigned molecule IDs.
            dump_frame_mol_ids: Set of molecule IDs found in dump frame.

        Returns:
            True if all spec mol_ids exist in dump, False otherwise.
        """
        if not spec.groups or not dump_frame_mol_ids:
            return False

        all_spec_ids: set[int] = set()
        for mol_ids in spec.groups.values():
            all_spec_ids.update(mol_ids)

        missing = all_spec_ids - dump_frame_mol_ids
        if missing:
            logger.warning(
                f"mol-ID verification failed: {len(missing)} IDs not in dump. "
                f"Sample missing: {sorted(missing)[:5]}"
            )
            return False

        return True


class LayerGroupAssignmentBuilder:
    """Build GroupEnergySpec from layer lineage metadata.

    Creates atom-ID-range-based groups for layered systems,
    enabling pairwise inter-layer energy decomposition via
    LAMMPS compute group/group.
    """

    def build(self, layer_lineage: list[dict]) -> GroupEnergySpec:
        """Construct GroupEnergySpec from layer lineage.

        Args:
            layer_lineage: List of dicts with keys:
                index (int), type (str), atom_id_start (int),
                atom_id_end (int).

        Returns:
            GroupEnergySpec with v2 group_selectors, all pairwise pairs,
            and layer_count.
        """
        if not layer_lineage:
            return GroupEnergySpec()

        selectors: dict[str, GroupSelector] = {}
        atom_counts: dict[str, int] = {}

        for entry in layer_lineage:
            idx = int(entry["index"])
            name = f"layer_{idx}"
            start = int(entry["atom_id_start"])
            end = int(entry["atom_id_end"])
            selectors[name] = GroupSelector(
                mode="atom_id_range",
                range_start=start,
                range_end=end,
            )
            atom_counts[name] = end - start + 1

        # Generate all pairwise combinations
        layer_names = sorted(selectors.keys())
        pairs: list[GroupPairSpec] = []
        for la, lb in combinations(layer_names, 2):
            i = int(la.split("_")[1])
            j = int(lb.split("_")[1])
            pairs.append(
                GroupPairSpec(
                    label=f"L{i}_L{j}",
                    group_a=la,
                    group_b=lb,
                )
            )

        logger.info(
            "Built layer group assignment: %d layers, %d pairs",
            len(selectors),
            len(pairs),
        )

        return GroupEnergySpec(
            group_selectors=selectors,
            pairs=pairs,
            atom_counts=atom_counts,
            layer_count=len(layer_lineage),
        )
