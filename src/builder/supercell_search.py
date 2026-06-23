"""Search utilities for target-aware rectangular supercells."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CrystalSizeEntry:
    """One available supercell size within a scan range."""

    lx: float
    ly: float
    avg_xy: float  # (lx+ly)/2
    anisotropy_pct: float  # |lx-ly|/avg * 100
    det: int
    matrix: tuple[tuple[int, int], tuple[int, int]]


# Module-level cache keyed by the full scan/search parameter set.
_SIZE_CACHE: dict[tuple, list[CrystalSizeEntry]] = {}


def _best_nz(target_z: float, cell_z: float, min_frac: float = 0.8) -> int:
    """Pick nz that best matches *target_z*.

    Uses ``round()`` by default, but falls back to ``ceil()`` when the
    rounded value yields a slab thinner than ``min_frac * target_z``.
    This prevents pathologically thin slabs for materials with large
    unit-cell *c* parameters (e.g. CaCO3 c=17.06 Å).
    """
    safe_c = max(cell_z, 1e-12)
    nz = max(1, round(target_z / safe_c))
    if nz * safe_c < target_z * min_frac:
        nz = max(1, math.ceil(target_z / safe_c))
    return nz


def enumerate_available_sizes(
    *,
    a: float,
    b: float,
    gamma_deg: float,
    c: float,
    xy_min: float = 35.0,
    xy_max: float = 60.0,
    target_z: float = 25.0,
    max_cells_xy: int = 200,
    ortho_tol: float = 1e-8,
    scan_step: float = 0.5,
) -> list[CrystalSizeEntry]:
    """Dynamically enumerate all distinct supercell sizes in [xy_min, xy_max].

    Repeatedly calls :func:`find_optimal_supercell` at ``scan_step`` intervals
    and collects distinct ``(lx, ly)`` pairs.  Results are cached per lattice
    parameter set so repeated calls are free.

    Args:
        a, b, gamma_deg, c: Unit cell parameters.
        xy_min: Lower bound of XY scan range (Angstrom).
        xy_max: Upper bound of XY scan range (Angstrom).
        target_z: Target slab thickness (Angstrom).
        max_cells_xy: Maximum determinant for supercell search.
        ortho_tol: Orthogonality tolerance.
        scan_step: Step size for scanning target_xy (Angstrom).

    Returns:
        Sorted list of :class:`CrystalSizeEntry` by ``avg_xy``.
    """
    cache_key = (
        a,
        b,
        gamma_deg,
        c,
        xy_min,
        xy_max,
        target_z,
        max_cells_xy,
        ortho_tol,
        scan_step,
    )
    if cache_key in _SIZE_CACHE:
        return _SIZE_CACHE[cache_key]

    seen: dict[tuple[float, float], CrystalSizeEntry] = {}
    target = xy_min
    while target <= xy_max + scan_step * 0.5:
        result = find_optimal_supercell(
            a=a,
            b=b,
            gamma_deg=gamma_deg,
            c=c,
            target_xy=target,
            target_z=target_z,
            max_cells_xy=max_cells_xy,
            ortho_tol=ortho_tol,
        )
        # Round to avoid floating-point duplicates
        key = (round(result.lx, 6), round(result.ly, 6))
        avg = (result.lx + result.ly) / 2.0
        if xy_min - 1.0 <= avg <= xy_max + 1.0 and key not in seen:
            aniso = abs(result.lx - result.ly) / max(avg, 1e-12) * 100.0
            seen[key] = CrystalSizeEntry(
                lx=result.lx,
                ly=result.ly,
                avg_xy=avg,
                anisotropy_pct=aniso,
                det=result.det,
                matrix=result.matrix,
            )
        target += scan_step

    entries = sorted(seen.values(), key=lambda e: e.avg_xy)
    _SIZE_CACHE[cache_key] = entries
    return entries


def find_best_match_for_target(
    *,
    a: float,
    b: float,
    gamma_deg: float,
    c: float,
    target_lx: float,
    target_ly: float,
    xy_margin: float = 5.0,
    target_z: float = 25.0,
    max_cells_xy: int = 200,
    ortho_tol: float = 1e-8,
    scan_step: float = 0.5,
) -> CrystalSizeEntry | None:
    """Find the supercell size closest to ``target_lx`` / ``target_ly``.

    Searches the range ``[avg - xy_margin, avg + xy_margin]`` where
    ``avg = (target_lx + target_ly) / 2``, then picks the entry that
    minimises ``max(|lx - target_lx|, |ly - target_ly|)``.

    Returns:
        Best matching :class:`CrystalSizeEntry`, or *None* if no sizes
        are available in the scan range.
    """
    avg_target = (target_lx + target_ly) / 2.0
    sizes = enumerate_available_sizes(
        a=a,
        b=b,
        gamma_deg=gamma_deg,
        c=c,
        xy_min=max(1.0, avg_target - xy_margin),
        xy_max=avg_target + xy_margin,
        target_z=target_z,
        max_cells_xy=max_cells_xy,
        ortho_tol=ortho_tol,
        scan_step=scan_step,
    )
    if not sizes:
        return None
    return min(
        sizes,
        key=lambda e: max(abs(e.lx - target_lx), abs(e.ly - target_ly)),
    )


@dataclass(frozen=True)
class SupercellResult:
    """Search result for an XY supercell."""

    matrix: tuple[tuple[int, int], tuple[int, int]]
    det: int
    nz: int
    lx: float
    ly: float
    lz: float
    orthogonality_error: float
    error_xy_pct: float
    is_diagonal: bool
    fallback_reason: str | None = None


def _lattice_vectors(
    a: float, b: float, gamma_deg: float
) -> tuple[tuple[float, float], tuple[float, float]]:
    gamma_rad = math.radians(gamma_deg)
    return (a, 0.0), (b * math.cos(gamma_rad), b * math.sin(gamma_rad))


def _vector_from_coeffs(
    p: int,
    q: int,
    a_vec: tuple[float, float],
    b_vec: tuple[float, float],
) -> tuple[float, float, float]:
    x = p * a_vec[0] + q * b_vec[0]
    y = p * a_vec[1] + q * b_vec[1]
    return x, y, math.hypot(x, y)


def _diagonal_result(
    *,
    a: float,
    b: float,
    gamma_deg: float,
    c: float,
    target_xy: float,
    target_z: float,
    min_nz: int,
    fallback_reason: str | None,
) -> SupercellResult:
    sin_gamma = math.sin(math.radians(gamma_deg))
    cell_x = max(a, 1e-12)
    cell_y = max(abs(b * sin_gamma), 1e-12)
    cell_z = max(c, 1e-12)

    nx = max(1, round(target_xy / cell_x))
    ny = max(1, round(target_xy / cell_y))
    nz = max(int(min_nz), _best_nz(target_z, cell_z))
    lx = nx * cell_x
    ly = ny * cell_y
    lz = nz * cell_z
    error_xy_pct = max(abs(lx - target_xy), abs(ly - target_xy)) / max(target_xy, 1e-12) * 100.0

    return SupercellResult(
        matrix=((nx, 0), (0, ny)),
        det=nx * ny,
        nz=nz,
        lx=lx,
        ly=ly,
        lz=lz,
        orthogonality_error=abs(math.cos(math.radians(gamma_deg))),
        error_xy_pct=error_xy_pct,
        is_diagonal=True,
        fallback_reason=fallback_reason,
    )


def find_optimal_supercell(
    *,
    a: float,
    b: float,
    gamma_deg: float,
    c: float,
    target_xy: float,
    target_z: float,
    max_cells_xy: int = 200,
    ortho_tol: float = 1e-8,
    min_nz: int = 1,
) -> SupercellResult:
    """Find a near-target rectangular supercell from 2x2 integer transformations."""

    if target_xy <= 0:
        raise ValueError("target_xy must be positive")
    if target_z <= 0:
        raise ValueError("target_z must be positive")
    if math.isclose(gamma_deg, 90.0, abs_tol=1e-8):
        return _diagonal_result(
            a=a,
            b=b,
            gamma_deg=gamma_deg,
            c=c,
            target_xy=target_xy,
            target_z=target_z,
            min_nz=min_nz,
            fallback_reason=None,
        )

    a_vec, b_vec = _lattice_vectors(a, b, gamma_deg)
    sin_gamma = math.sin(math.radians(gamma_deg))
    min_step = min(abs(a), abs(b * sin_gamma))
    if min_step <= 1e-12:
        raise ValueError(f"Unsupported gamma for supercell search: {gamma_deg}")

    search_radius = max(1, math.ceil(target_xy / min_step) + 3)
    margin = 2.0 * max(abs(a), abs(b))

    candidates: list[tuple[int, int, float, float, float]] = []
    for p in range(-search_radius, search_radius + 1):
        for q in range(-search_radius, search_radius + 1):
            if p == 0 and q == 0:
                continue
            ax, ay, la = _vector_from_coeffs(p, q, a_vec, b_vec)
            if abs(la - target_xy) <= margin:
                candidates.append((p, q, ax, ay, la))

    if not candidates:
        return _diagonal_result(
            a=a,
            b=b,
            gamma_deg=gamma_deg,
            c=c,
            target_xy=target_xy,
            target_z=target_z,
            min_nz=min_nz,
            fallback_reason="no_candidate_vectors",
        )

    best_result: SupercellResult | None = None
    best_rank: tuple[float, int, float, int] | None = None
    nz = max(int(min_nz), _best_nz(target_z, c))
    lz = nz * c

    for p, q, ax, ay, la in candidates:
        for r, s, bx, by, lb in candidates:
            det = p * s - q * r
            if det <= 0 or det > max_cells_xy:
                continue

            dot = ax * bx + ay * by
            denom = max(la * lb, 1e-12)
            orthogonality_error = abs(dot / denom)
            if orthogonality_error > ortho_tol:
                continue

            error_xy_pct = (
                max(abs(la - target_xy), abs(lb - target_xy)) / max(target_xy, 1e-12) * 100.0
            )
            rank = (
                ((la - target_xy) / target_xy) ** 2 + ((lb - target_xy) / target_xy) ** 2,
                det,
                abs(la - lb),
                abs(p) + abs(q) + abs(r) + abs(s),
            )
            result = SupercellResult(
                matrix=((p, q), (r, s)),
                det=det,
                nz=nz,
                lx=la,
                ly=lb,
                lz=lz,
                orthogonality_error=orthogonality_error,
                error_xy_pct=error_xy_pct,
                is_diagonal=(q == 0 and r == 0),
                fallback_reason=None,
            )
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_result = result

    diagonal_result = _diagonal_result(
        a=a,
        b=b,
        gamma_deg=gamma_deg,
        c=c,
        target_xy=target_xy,
        target_z=target_z,
        min_nz=min_nz,
        fallback_reason="no_better_orthogonal_candidate",
    )

    if best_result is not None and best_result.error_xy_pct + 1e-6 < diagonal_result.error_xy_pct:
        return best_result

    if best_result is None:
        return _diagonal_result(
            a=a,
            b=b,
            gamma_deg=gamma_deg,
            c=c,
            target_xy=target_xy,
            target_z=target_z,
            min_nz=min_nz,
            fallback_reason="no_orthogonal_candidate",
        )

    return diagonal_result


def enumerate_unit_cells(
    matrix: tuple[tuple[int, int], tuple[int, int]],
    *,
    tol: float = 1e-9,
) -> list[tuple[int, int]]:
    """Return integer unit-cell origins contained in the transformed supercell."""

    (p, q), (r, s) = matrix
    det = p * s - q * r
    if det <= 0:
        raise ValueError(f"matrix must have positive determinant, got {det}")

    corners = ((0, 0), (p, q), (r, s), (p + r, q + s))
    min_i = min(c[0] for c in corners) - 1
    max_i = max(c[0] for c in corners) + 1
    min_j = min(c[1] for c in corners) - 1
    max_j = max(c[1] for c in corners) + 1

    cells: list[tuple[int, int]] = []
    for i in range(min_i, max_i + 1):
        for j in range(min_j, max_j + 1):
            u_num = s * i - r * j
            v_num = -q * i + p * j
            if 0 <= u_num < det and 0 <= v_num < det:
                cells.append((i, j))

    if len(cells) != det:
        raise AssertionError(f"enumeration mismatch: got {len(cells)} cells for det={det}")
    return cells
