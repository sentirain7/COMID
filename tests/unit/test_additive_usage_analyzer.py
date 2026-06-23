"""Tests for additive usage analyzer."""

import sys

sys.path.insert(0, "src")

from orchestrator.additive_usage_analyzer import compute_coverage_report


def _catalog():
    return [
        {
            "mol_id": "ADD_001",
            "short_name": "SBS",
            "category": "polymer",
            "subcategory": "polymer",
            "functional_tags": ["modifier"],
        },
        {
            "mol_id": "ADD_002",
            "short_name": "PPA",
            "category": "polymer",
            "subcategory": "polymer",
            "functional_tags": ["anti-stripping"],
        },
        {
            "mol_id": "ADD_003",
            "short_name": "Lignin",
            "category": "bio",
            "subcategory": "bio",
            "functional_tags": ["anti-aging"],
        },
    ]


def _completed_rows():
    return [
        {
            "exp_id": "exp-1",
            "additive_type": "SBS",
            "additive_wt_pct": 5.0,
            "temperature_K": 293.0,
            "metadata_json": {"binder_type": "AAA1"},
            "status": "completed",
        },
        {
            "exp_id": "exp-2",
            "additive_type": "SBS",
            "additive_wt_pct": 5.0,
            "temperature_K": 313.0,
            "metadata_json": {"binder_type": "AAA1"},
            "status": "completed",
        },
    ]


def test_empty_catalog():
    report = compute_coverage_report(catalog_additives=[], completed_rows=[])
    assert report.total_catalog == 0
    assert report.coverage_fraction == 0.0


def test_no_completed_experiments():
    report = compute_coverage_report(
        catalog_additives=_catalog(),
        completed_rows=[],
    )
    assert report.total_catalog == 3
    assert len(report.untested_additives) == 3
    assert len(report.tested_additives) == 0
    assert report.coverage_fraction == 0.0
    assert len(report.gaps) > 0


def test_partial_coverage():
    report = compute_coverage_report(
        catalog_additives=_catalog(),
        completed_rows=_completed_rows(),
    )
    assert report.total_catalog == 3
    assert "SBS" in report.tested_additives
    assert "PPA" in report.untested_additives
    assert "Lignin" in report.untested_additives
    assert 0.0 < report.coverage_fraction < 1.0


def test_ranked_gaps_sorted_by_novelty():
    report = compute_coverage_report(
        catalog_additives=_catalog(),
        completed_rows=_completed_rows(),
    )
    assert len(report.ranked_gaps) > 0
    scores = [g.novelty_score for g in report.ranked_gaps]
    assert scores == sorted(scores, reverse=True)


def test_untested_category_has_higher_novelty():
    report = compute_coverage_report(
        catalog_additives=_catalog(),
        completed_rows=_completed_rows(),
    )
    # Lignin (bio category, untested) should rank higher than PPA (polymer, tested category)
    lignin_gaps = [g for g in report.ranked_gaps if g.additive_type == "Lignin"]
    ppa_gaps = [g for g in report.ranked_gaps if g.additive_type == "PPA"]
    if lignin_gaps and ppa_gaps:
        assert lignin_gaps[0].novelty_score >= ppa_gaps[0].novelty_score


def test_skips_non_completed_rows():
    rows = [
        {
            "exp_id": "exp-fail",
            "additive_type": "SBS",
            "additive_wt_pct": 5.0,
            "temperature_K": 293.0,
            "metadata_json": {"binder_type": "AAA1"},
            "status": "failed",
        },
    ]
    report = compute_coverage_report(
        catalog_additives=_catalog(),
        completed_rows=rows,
    )
    assert "SBS" not in report.tested_additives


def test_full_coverage():
    """All cells covered → coverage_fraction near 1.0."""
    catalog = [{"mol_id": "ADD_001", "short_name": "SBS", "category": "polymer"}]
    rows = [
        {
            "exp_id": f"exp-{i}",
            "additive_type": "SBS",
            "additive_wt_pct": 5.0,
            "temperature_K": temp,
            "metadata_json": {"binder_type": "AAA1"},
            "status": "completed",
        }
        for i, temp in enumerate([293.0, 313.0])
    ]
    report = compute_coverage_report(catalog_additives=catalog, completed_rows=rows)
    assert report.coverage_fraction == 1.0
    assert len(report.gaps) == 0
