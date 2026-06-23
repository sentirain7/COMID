"""Unit tests for target-aware supercell search."""

import math

import pytest

from builder.supercell_search import enumerate_unit_cells, find_optimal_supercell


def _diagonal_error(a: float, b: float, gamma_deg: float, target_xy: float) -> float:
    sin_gamma = math.sin(math.radians(gamma_deg))
    lx = max(1, round(target_xy / a)) * a
    ly = max(1, round(target_xy / (b * sin_gamma))) * b * sin_gamma
    return max(abs(lx - target_xy), abs(ly - target_xy)) / target_xy * 100.0


def test_cubic_returns_diagonal_result():
    result = find_optimal_supercell(
        a=4.213,
        b=4.213,
        gamma_deg=90.0,
        c=4.213,
        target_xy=40.0,
        target_z=12.0,
    )

    assert result.is_diagonal is True
    assert result.matrix[0][1] == 0
    assert result.matrix[1][0] == 0


def test_hexagonal_improves_error_over_diagonal():
    diagonal_error = _diagonal_error(a=2.0, b=2.5, gamma_deg=120.0, target_xy=14.0)
    result = find_optimal_supercell(
        a=2.0,
        b=2.5,
        gamma_deg=120.0,
        c=3.5,
        target_xy=14.0,
        target_z=7.0,
        max_cells_xy=200,
        ortho_tol=1e-8,
    )

    assert result.fallback_reason is None
    assert result.error_xy_pct < diagonal_error


def test_strict_orthogonality_is_respected():
    result = find_optimal_supercell(
        a=4.990,
        b=4.990,
        gamma_deg=120.0,
        c=17.062,
        target_xy=40.0,
        target_z=17.2,
        max_cells_xy=200,
        ortho_tol=1e-8,
    )

    if result.fallback_reason is None:
        assert result.orthogonality_error <= 1e-8
    else:
        assert result.fallback_reason in {
            "no_orthogonal_candidate",
            "no_better_orthogonal_candidate",
        }


def test_det_matches_enumeration():
    result = find_optimal_supercell(
        a=2.0,
        b=2.5,
        gamma_deg=120.0,
        c=3.5,
        target_xy=14.0,
        target_z=7.0,
    )
    cells = enumerate_unit_cells(result.matrix)
    assert len(cells) == result.det


def test_diagonal_enumeration_identity():
    cells = enumerate_unit_cells(((3, 0), (0, 4)))
    assert len(cells) == 12
    assert (0, 0) in cells
    assert (2, 3) in cells


def test_non_diagonal_enumeration():
    cells = enumerate_unit_cells(((2, 1), (0, 3)))
    assert len(cells) == 6


def test_fallback_reason_populated_when_no_exact_candidate():
    result = find_optimal_supercell(
        a=4.0,
        b=5.0,
        gamma_deg=100.0,
        c=6.0,
        target_xy=20.0,
        target_z=12.0,
        max_cells_xy=20,
        ortho_tol=1e-10,
    )

    assert result.fallback_reason is not None
    assert result.is_diagonal is True


def test_invalid_det_matrix_rejected():
    with pytest.raises(ValueError, match="positive determinant"):
        enumerate_unit_cells(((1, 0), (0, 0)))
