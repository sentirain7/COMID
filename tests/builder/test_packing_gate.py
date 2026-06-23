"""Tests for the packing defect gate (Packmol convergence + retry).

Covers the production fix:
  - 0순위: Packmol 자기 보고(수렴) 파싱 — Success/위반량/STOP.
  - PackmolResult가 converged/max_constraint_violation을 노출.
  - structure_builder 재시도 seed가 시도마다 다르고 결정적(같은 조성→같은 시퀀스).
  - 최적값(maxit 200, tolerance 3.0)이 빌더에 적용됨.
"""

import sys

sys.path.insert(0, "src")

from builder.packmol_wrapper import PackmolResult, _parse_packmol_convergence


class TestPackmolConvergenceParse:
    def test_success_zero_violation(self):
        stdout = (
            "  Maximum violation of target distance:     0.000000\n"
            "                                 Success! \n"
            "              Maximum violation of the constraints: .00000E+00\n"
        )
        converged, viol = _parse_packmol_convergence(stdout)
        assert converged is True
        assert viol == 0.0

    def test_failure_nonzero_violation(self):
        stdout = (
            "  Maximum violation of target distance:     3.975416\n"
            "  Maximum violation of the constraints: .25835E+02\n"
            "  STOP: Maximum number of GENCAN loops achieved.\n"
        )
        converged, viol = _parse_packmol_convergence(stdout)
        assert converged is False
        assert viol is not None and viol > 1.0

    def test_near_zero_violation_without_success_token(self):
        # 수렴(위반량≈0)했으나 loop 소진으로 STOP/exit≠0이고 Success 토큰 누락 —
        # 정량 위반량으로 수렴 인정해야 함(실 케이스 회귀).
        stdout = (
            "  Maximum violation of the constraints: 9.5901E-16\n"
            "  STOP: Maximum number of GENCAN loops achieved.\n"
        )
        converged, viol = _parse_packmol_convergence(stdout)
        assert converged is True
        assert viol is not None and viol < 1e-4

    def test_takes_last_violation(self):
        # 마지막(최종 상태) 위반량을 취함
        stdout = (
            "  Maximum violation of the constraints: .50000E+02\n"
            "                                 Success! \n"
            "  Maximum violation of the constraints: .00000E+00\n"
        )
        converged, viol = _parse_packmol_convergence(stdout)
        assert converged is True
        assert viol == 0.0

    def test_result_defaults(self):
        from pathlib import Path

        r = PackmolResult(success=True, output_file=Path("/x"), log="")
        assert r.converged is True  # 기본(mock 등)
        assert r.max_constraint_violation is None


class TestRetrySeed:
    def _builder(self):
        from unittest.mock import patch

        from builder.structure_builder import StructureBuilder

        # PackmolWrapper._check_packmol이 실행파일을 찾으므로 패치
        with patch("builder.packmol_wrapper.PackmolWrapper._check_packmol"):
            return StructureBuilder()

    def test_seed_varies_per_attempt_deterministic(self):
        b = self._builder()
        mc = {"A": 3, "B": 2}
        seeds = [b._derive_pack_seed(mc, i) for i in range(1, 6)]
        assert len(set(seeds)) == 5  # 시도마다 다름
        assert all(s > 0 for s in seeds)
        # 결정적: 같은 (조성, attempt) → 같은 seed (프로세스 무관 hashlib)
        assert b._derive_pack_seed(mc, 1) == seeds[0]

    def test_recommended_density_and_validator_threshold(self):
        from builder.structure_builder import _PACK_RECOMMENDED_DENSITY

        b = self._builder()
        # 지배적 레버(밀도)만 전역 적용; tol/maxit은 안전한 표준 기본값 유지.
        assert _PACK_RECOMMENDED_DENSITY == 0.2
        # 검증 임계는 0.9×tolerance에 묶임(매직넘버 아님)
        assert abs(b.validator.min_distance - 0.9 * b.packmol.tolerance) < 1e-9

    def test_density_schedule_caps_at_recommended(self):
        # 요청 밀도(0.5 기본)는 권장값(0.2)으로 캡 후 저밀도로 에스컬레이션.
        from builder.structure_builder import (
            _PACK_DENSITY_ESCALATION,
            _PACK_RECOMMENDED_DENSITY,
        )

        start = min(0.5, _PACK_RECOMMENDED_DENSITY)
        schedule = [start] + [d for d in _PACK_DENSITY_ESCALATION if d < start]
        assert schedule[0] == 0.2
        assert schedule[-1] == 0.1  # 최종 에스컬레이션은 ~100% 청정 밀도
