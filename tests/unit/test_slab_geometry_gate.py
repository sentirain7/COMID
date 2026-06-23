"""Slab 기하 빌드 게이트 테스트 (보완 #5).

XY/Z 종횡비·진공/슬랩두께 비율을 정책 SSOT(layer.py) 기준으로 검증하고,
하한(hard) 미만이면 빌드 게이트가 'fail'을 내는지 확인한다.
"""

import sys
from types import SimpleNamespace

sys.path.insert(0, "src")

from contracts.policies.layer import DEFAULT_LAYER_POLICY  # noqa: E402
from contracts.schemas import LayerSourceType  # noqa: E402
from features.layered_structures.service import _validate_checks  # noqa: E402


def _src(lx, ly, lz, source_type=LayerSourceType.BINDER_CELL, source_id="b"):
    return SimpleNamespace(
        source_type=source_type,
        source_id=source_id,
        box_size=(float(lx), float(ly), float(lz)),
        boundary_mode="ppf",
    )


def _by_code(checks, code):
    return next(c for c in checks if c.code == code)


class TestPolicyFields:
    def test_hard_below_warn(self):
        p = DEFAULT_LAYER_POLICY
        assert p.min_xy_to_z_ratio_hard < p.min_xy_to_z_ratio_warn
        assert p.min_vacuum_to_slab_ratio_hard < p.min_vacuum_to_slab_ratio_warn

    def test_preview_request_exposes_z_vacuum(self):
        # P0-1: 게이트가 실제 진공값을 보도록 preview 요청에 필드가 노출돼야 한다.
        from api.schemas.structures import LayeredStructurePreviewRequest

        req = LayeredStructurePreviewRequest(
            layers=[
                {"source_type": "crystal_structure", "source_id": "c1"},
                {"source_type": "binder_cell", "source_id": "b1"},
            ],
            z_vacuum_angstrom=120.0,
        )
        assert req.z_vacuum_angstrom == 120.0
        # 미지정은 None(서비스가 정책 기본으로 해석)
        req2 = LayeredStructurePreviewRequest(
            layers=[
                {"source_type": "crystal_structure", "source_id": "c1"},
                {"source_type": "binder_cell", "source_id": "b1"},
            ]
        )
        assert req2.z_vacuum_angstrom is None

    def test_schema_default_uses_policy(self):
        from api.schemas.structures import LayeredStructurePreviewRequest

        req = LayeredStructurePreviewRequest(
            layers=[
                {"source_type": "crystal_structure", "source_id": "c1"},
                {"source_type": "binder_cell", "source_id": "b1"},
            ]
        )
        assert req.min_xy_to_z_ratio == DEFAULT_LAYER_POLICY.min_xy_to_z_ratio_warn


class TestAspectRatioGate:
    def _run(self, sources, min_ratio=None):
        return _validate_checks(
            sources,
            xy_tolerance_pct=50.0,
            min_xy_to_z_ratio=min_ratio or DEFAULT_LAYER_POLICY.min_xy_to_z_ratio_warn,
        )

    def test_fail_when_below_hard(self):
        # XY=10, total_z=60 → ratio 0.167 < hard(0.5) → fail
        checks = self._run([_src(10, 10, 30), _src(10, 10, 30)])
        assert _by_code(checks, "aspect_ratio").status == "fail"

    def test_warn_between_hard_and_warn(self):
        # XY=100, total_z=80 → ratio 1.25 ... need between 0.5 and 1.2
        # XY=70, total_z=80 → 0.875 (0.5<.<1.2) → warn
        checks = self._run([_src(70, 70, 40), _src(70, 70, 40)])
        assert _by_code(checks, "aspect_ratio").status == "warn"

    def test_pass_above_warn(self):
        # XY=100, total_z=40 → ratio 2.5 → pass
        checks = self._run([_src(100, 100, 20), _src(100, 100, 20)])
        assert _by_code(checks, "aspect_ratio").status == "pass"


class TestSlabVacuumGate:
    def _run(self, sources, z_vacuum=None):
        kw = {}
        if z_vacuum is not None:
            kw["z_vacuum_angstrom"] = z_vacuum
        return _validate_checks(
            sources,
            xy_tolerance_pct=50.0,
            min_xy_to_z_ratio=DEFAULT_LAYER_POLICY.min_xy_to_z_ratio_warn,
            **kw,
        )

    def test_pass_thin_slab(self):
        # total_z=40, vacuum=40 → ratio 1.0 → pass (>= warn 1.0)
        checks = self._run([_src(100, 100, 20), _src(100, 100, 20)], z_vacuum=20.0)
        assert _by_code(checks, "slab_vacuum_ratio").status == "pass"

    def test_warn_moderate_slab(self):
        # total_z=80, vacuum=40 → ratio 0.5 (0.3<.<1.0) → warn
        checks = self._run([_src(200, 200, 40), _src(200, 200, 40)], z_vacuum=20.0)
        assert _by_code(checks, "slab_vacuum_ratio").status == "warn"

    def test_fail_thick_slab(self):
        # total_z=200, vacuum=40 → ratio 0.2 < hard(0.3) → fail
        checks = self._run([_src(400, 400, 100), _src(400, 400, 100)], z_vacuum=20.0)
        assert _by_code(checks, "slab_vacuum_ratio").status == "fail"

    def test_larger_vacuum_recovers_pass(self):
        # total_z=200 but vacuum=120 → ratio 1.2 → pass
        checks = self._run([_src(400, 400, 100), _src(400, 400, 100)], z_vacuum=120.0)
        assert _by_code(checks, "slab_vacuum_ratio").status == "pass"
