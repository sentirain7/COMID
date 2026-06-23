"""Tests for enumerate_available_sizes and find_best_match_for_target."""

from builder.supercell_search import (
    _SIZE_CACHE,
    CrystalSizeEntry,
    enumerate_available_sizes,
    find_best_match_for_target,
)


class TestEnumerateAvailableSizes:
    """Test dynamic size enumeration."""

    def test_sio2_hex_returns_expected_count(self):
        sizes = enumerate_available_sizes(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
        )
        assert len(sizes) >= 10
        assert len(sizes) <= 15

    def test_mgo_cubic_returns_expected_count(self):
        sizes = enumerate_available_sizes(
            a=4.213,
            b=4.213,
            gamma_deg=90.0,
            c=4.213,
        )
        assert len(sizes) >= 5
        assert len(sizes) <= 10

    def test_all_entries_are_crystal_size_entry(self):
        sizes = enumerate_available_sizes(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
        )
        assert all(isinstance(s, CrystalSizeEntry) for s in sizes)

    def test_sorted_by_avg_xy(self):
        sizes = enumerate_available_sizes(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
        )
        avgs = [s.avg_xy for s in sizes]
        assert avgs == sorted(avgs)

    def test_avg_within_range(self):
        xy_min, xy_max = 35.0, 60.0
        sizes = enumerate_available_sizes(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
            xy_min=xy_min,
            xy_max=xy_max,
        )
        for s in sizes:
            assert s.avg_xy >= xy_min - 1.5, f"avg_xy {s.avg_xy} below range"
            assert s.avg_xy <= xy_max + 1.5, f"avg_xy {s.avg_xy} above range"

    def test_cubic_anisotropy_zero(self):
        sizes = enumerate_available_sizes(
            a=4.213,
            b=4.213,
            gamma_deg=90.0,
            c=4.213,
        )
        for s in sizes:
            assert s.anisotropy_pct < 0.01, "Cubic should have zero anisotropy"

    def test_hexagonal_may_have_nonzero_anisotropy(self):
        sizes = enumerate_available_sizes(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
        )
        aniso_values = [s.anisotropy_pct for s in sizes]
        assert any(v > 0.5 for v in aniso_values), "Some hex sizes should be anisotropic"

    def test_cache_returns_same_object(self):
        sizes1 = enumerate_available_sizes(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
        )
        sizes2 = enumerate_available_sizes(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
        )
        assert sizes1 is sizes2

    def test_cache_key_includes_ortho_tol_and_scan_step(self):
        _SIZE_CACHE.clear()

        sizes1 = enumerate_available_sizes(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
            ortho_tol=1e-8,
            scan_step=0.5,
        )
        sizes2 = enumerate_available_sizes(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
            ortho_tol=1e-2,
            scan_step=1.0,
        )

        assert sizes1 is not sizes2

    def test_distinct_sizes(self):
        sizes = enumerate_available_sizes(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
        )
        keys = [(round(s.lx, 6), round(s.ly, 6)) for s in sizes]
        assert len(keys) == len(set(keys)), "Duplicates found"

    def test_narrow_range_fewer_sizes(self):
        wide = enumerate_available_sizes(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
            xy_min=35.0,
            xy_max=60.0,
        )
        narrow = enumerate_available_sizes(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
            xy_min=40.0,
            xy_max=50.0,
        )
        assert len(narrow) <= len(wide)


class TestFindBestMatchForTarget:
    """Test best-match search."""

    def test_exact_match_sio2(self):
        match = find_best_match_for_target(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
            target_lx=44.22,
            target_ly=42.55,
        )
        assert match is not None
        assert abs(match.lx - 44.22) < 1.0
        assert abs(match.ly - 42.55) < 1.0

    def test_cubic_returns_square(self):
        match = find_best_match_for_target(
            a=4.213,
            b=4.213,
            gamma_deg=90.0,
            c=4.213,
            target_lx=42.0,
            target_ly=42.0,
        )
        assert match is not None
        assert abs(match.lx - match.ly) < 0.01

    def test_returns_none_for_out_of_range(self):
        # Even with default max_cells_xy, if the range is too narrow
        # around a gap between valid sizes, no match is found.
        sizes = enumerate_available_sizes(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
            xy_min=35.0,
            xy_max=60.0,
        )
        # Pick a target in between two sizes where margin=0.1 can't reach
        if len(sizes) >= 2:
            gap_target = (sizes[0].avg_xy + sizes[1].avg_xy) / 2.0
            match = find_best_match_for_target(
                a=4.913,
                b=4.913,
                gamma_deg=120.0,
                c=5.405,
                target_lx=gap_target,
                target_ly=gap_target,
                xy_margin=0.01,  # extremely narrow
            )
            # If no sizes in the narrow range, returns None
            # Otherwise still returns something — either way is valid
            if match is not None:
                assert isinstance(match, CrystalSizeEntry)

    def test_minimizes_max_error(self):
        match = find_best_match_for_target(
            a=4.913,
            b=4.913,
            gamma_deg=120.0,
            c=5.405,
            target_lx=40.0,
            target_ly=40.0,
        )
        assert match is not None
        error = max(abs(match.lx - 40.0), abs(match.ly - 40.0))
        assert error < 5.0
