"""Additive usage analyzer — coverage and gap analysis for exploration planning."""

from __future__ import annotations

from dataclasses import dataclass, field

from common.logging import get_logger
from contracts.policies.exploration_policy import DEFAULT_EXPLORATION_POLICY

logger = get_logger("orchestrator.additive_usage_analyzer")


@dataclass
class AdditiveGap:
    """A single untested additive-condition cell."""

    additive_type: str
    binder_type: str
    temperature_k: float
    concentration: float
    novelty_score: float = 0.0


@dataclass
class AdditiveCoverageReport:
    """Full coverage analysis result."""

    total_catalog: int = 0
    tested_additives: list[str] = field(default_factory=list)
    untested_additives: list[str] = field(default_factory=list)
    coverage_fraction: float = 0.0
    gaps: list[AdditiveGap] = field(default_factory=list)
    ranked_gaps: list[AdditiveGap] = field(default_factory=list)
    cells_total: int = 0
    cells_covered: int = 0


def compute_coverage_report(
    *,
    catalog_additives: list[dict[str, object]],
    completed_rows: list[dict[str, object]],
    policy: object | None = None,
) -> AdditiveCoverageReport:
    """Compute additive coverage report from raw data.

    Args:
        catalog_additives: Active additive catalog entries.
            Each dict must have at least 'mol_id' or 'short_name'.
        completed_rows: Raw experiment rows from repository.
            Each dict must have: exp_id, additive_type, temperature_K, metadata_json, status.
        policy: Override exploration policy (default: DEFAULT_EXPLORATION_POLICY).

    Returns:
        AdditiveCoverageReport with tested/untested/gaps/ranked_gaps.
    """
    pol = policy or DEFAULT_EXPLORATION_POLICY

    # Extract catalog additive identifiers
    catalog_ids: set[str] = set()
    catalog_meta: dict[str, dict[str, object]] = {}
    for entry in catalog_additives:
        aid = str(entry.get("short_name") or entry.get("mol_id") or "").strip()
        if aid:
            catalog_ids.add(aid)
            catalog_meta[aid] = entry

    if not catalog_ids:
        return AdditiveCoverageReport()

    # Build coverage map: (additive, binder, temp, conc) → count
    covered_cells: dict[tuple[str, str, float, float], int] = {}
    tested_set: set[str] = set()

    for row in completed_rows:
        status = str(row.get("status") or "").lower()
        if status != "completed":
            continue

        additive_type = str(row.get("additive_type") or "").strip()
        if not additive_type:
            continue

        tested_set.add(additive_type)

        temp_k = float(row.get("temperature_K") or row.get("temperature_k") or 298.0)

        # Extract binder_type from metadata or exp_id
        metadata = row.get("metadata_json")
        if isinstance(metadata, dict):
            binder_type = str(metadata.get("binder_type") or "").strip()
        else:
            binder_type = ""

        if not binder_type:
            exp_id = str(row.get("exp_id") or "")
            binder_type = _parse_binder_from_exp_id(exp_id)

        # Extract concentration
        conc = float(row.get("additive_wt_pct") or 0.0)
        if conc <= 0:
            metadata = row.get("metadata_json")
            if isinstance(metadata, dict):
                conc = float(metadata.get("additive_wt_pct") or 0.0)

        cell_key = (additive_type, binder_type or "unknown", temp_k, conc)
        covered_cells[cell_key] = covered_cells.get(cell_key, 0) + 1

    # Generate all expected cells
    required_binders = list(pol.coverage.required_binder_types)
    required_temps = list(pol.coverage.required_temperatures_k)
    default_concs = list(pol.default_exploration_concentrations)

    all_gaps: list[AdditiveGap] = []
    cells_total = 0

    for aid in sorted(catalog_ids):
        for binder in required_binders:
            for temp in required_temps:
                for conc in default_concs:
                    cells_total += 1
                    cell_key = (aid, binder, temp, conc)
                    count = covered_cells.get(cell_key, 0)
                    if count < pol.coverage.min_completed_per_cell:
                        gap = AdditiveGap(
                            additive_type=aid,
                            binder_type=binder,
                            temperature_k=temp,
                            concentration=conc,
                        )
                        all_gaps.append(gap)

    cells_covered = cells_total - len(all_gaps)
    coverage_fraction = cells_covered / cells_total if cells_total > 0 else 0.0

    # Rank gaps by novelty
    ranked_gaps = _rank_gaps_by_novelty(all_gaps, catalog_meta, tested_set, pol)

    untested = sorted(catalog_ids - tested_set)
    tested = sorted(tested_set & catalog_ids)

    return AdditiveCoverageReport(
        total_catalog=len(catalog_ids),
        tested_additives=tested,
        untested_additives=untested,
        coverage_fraction=coverage_fraction,
        gaps=all_gaps,
        ranked_gaps=ranked_gaps,
        cells_total=cells_total,
        cells_covered=cells_covered,
    )


def _rank_gaps_by_novelty(
    gaps: list[AdditiveGap],
    catalog_meta: dict[str, dict[str, object]],
    tested_set: set[str],
    policy: object,
) -> list[AdditiveGap]:
    """Score and rank gaps by novelty weights."""
    if not gaps:
        return []

    # Collect all categories and functional tags from catalog
    all_categories: set[str] = set()
    tested_categories: set[str] = set()
    all_tags: set[str] = set()
    tested_tags: set[str] = set()

    for aid, meta in catalog_meta.items():
        cat = str(meta.get("category") or meta.get("subcategory") or "unknown")
        all_categories.add(cat)
        if aid in tested_set:
            tested_categories.add(cat)

        tags = meta.get("functional_tags") or []
        if isinstance(tags, list):
            for tag in tags:
                all_tags.add(str(tag))
                if aid in tested_set:
                    tested_tags.add(str(tag))

    weights = policy.novelty

    scored_gaps: list[AdditiveGap] = []
    for gap in gaps:
        meta = catalog_meta.get(gap.additive_type, {})

        # Category diversity: untested category → higher score
        cat = str(meta.get("category") or meta.get("subcategory") or "unknown")
        cat_score = 1.0 if cat not in tested_categories else 0.0

        # Functional tag gap
        tags = meta.get("functional_tags") or []
        if isinstance(tags, list) and tags:
            untested_tag_frac = sum(1 for t in tags if str(t) not in tested_tags) / len(tags)
        else:
            untested_tag_frac = 0.5

        # Descriptor distance: v1 always 0 (descriptor lookup not available)
        desc_score = 0.0

        # Literature prior: has literature links → higher weight
        lit_count = int(meta.get("literature_link_count") or 0)
        lit_score = min(lit_count / 5.0, 1.0) if lit_count > 0 else 0.3

        novelty = (
            weights.category_diversity_weight * cat_score
            + weights.functional_tag_gap_weight * untested_tag_frac
            + weights.descriptor_distance_weight * desc_score
            + weights.literature_prior_weight * lit_score
        )

        gap.novelty_score = round(novelty, 4)
        scored_gaps.append(gap)

    scored_gaps.sort(key=lambda g: g.novelty_score, reverse=True)
    return scored_gaps


def _parse_binder_from_exp_id(exp_id: str) -> str:
    """Best-effort binder type extraction from exp_id."""
    if not exp_id:
        return "unknown"
    try:
        from common.pathing import parse_exp_id

        parsed = parse_exp_id(exp_id)
        return str(parsed.get("binder_type") or "unknown")
    except Exception:
        # Fallback: try to extract from known patterns
        for bt in ("AAA1", "AAK1", "AAM1"):
            if bt.lower() in exp_id.lower():
                return bt
        return "unknown"
