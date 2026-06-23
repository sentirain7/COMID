"""정밀 E_inter 자동 활성화 정책 resolver 테스트 (원칙 #2: 계면 장거리 Coulomb 복원).

계면(layered) 실험은 정전기 지배적이라 GPU-only e_inter가 불완전하다. 명시 설정이
없을 때 정책이 RECOMMENDED/REQUIRED인 layered 실험은 정밀 CPU rerun을 자동 활성화한다.
bulk/일반 binder 경로는 정책상 RECOMMENDED가 아니므로 자동 활성화되지 않는다(opt-in 유지).
"""

import sys

sys.path.insert(0, "src")

import features.e_inter_compute.policy as policy_mod  # noqa: E402
from contracts.policies.e_inter_compute import (  # noqa: E402
    AUTO_ENABLE_PRECISE_EINTER_FOR_LAYERED,
    EInterComputeConfig,
    EInterPolicyInput,
)
from contracts.schema_enums import EInterComputeMode  # noqa: E402
from features.e_inter_compute.policy import resolve_default_einter_config  # noqa: E402


class TestSSOTFlag:
    def test_flag_is_bool_and_default_on(self):
        # 원칙 #2: 계면 정밀 e_inter 복원은 기본 활성(저비용 후처리).
        assert isinstance(AUTO_ENABLE_PRECISE_EINTER_FOR_LAYERED, bool)
        assert AUTO_ENABLE_PRECISE_EINTER_FOR_LAYERED is True


class TestResolveDefaultEInterConfig:
    def test_layered_2plus_auto_enables(self):
        cfg = resolve_default_einter_config(
            EInterPolicyInput(
                workflow="layered_structure",
                tier="screening",
                ff_type="bulk_ff_gaff2",
                layer_count=3,
            )
        )
        assert isinstance(cfg, EInterComputeConfig)
        assert cfg.enabled is True
        assert cfg.auto_trigger_rerun is True
        assert cfg.mode == EInterComputeMode.GPU_THEN_CPU
        assert cfg.metrics == ["e_inter_total"]

    def test_layered_required_when_long_range_metric_selected(self):
        cfg = resolve_default_einter_config(
            EInterPolicyInput(
                workflow="layered_structure",
                tier="confirm",
                layer_count=2,
                selected_metrics=("e_inter_layer_matrix",),
            )
        )
        assert cfg is not None
        assert cfg.enabled is True

    def test_single_layer_does_not_auto_enable(self):
        # layer_count<2 이면 RECOMMENDED 규칙 미충족 → None.
        cfg = resolve_default_einter_config(
            EInterPolicyInput(
                workflow="layered_structure",
                tier="screening",
                layer_count=1,
            )
        )
        assert cfg is None

    def test_binder_cell_without_additive_does_not_auto_enable(self):
        # 일반 SARA binder는 OPTIONAL → 자동 활성화 안 함(opt-in 유지, byte-identical).
        cfg = resolve_default_einter_config(
            EInterPolicyInput(
                workflow="binder_cell",
                tier="screening",
            )
        )
        assert cfg is None

    def test_recommended_level_auto_enables_regardless_of_workflow(self):
        # resolver는 순수 정책 함수 — 정책 level이 RECOMMENDED이면 config를 반환한다.
        # (binder+additive는 RECOMMENDED, score 0.6.) 단, 프로덕션에서는 layered
        # 제출 경로만 이 함수를 호출하므로 실제 자동 활성화는 계면 실험에 한정된다.
        cfg = resolve_default_einter_config(
            EInterPolicyInput(
                workflow="binder_cell",
                tier="screening",
                has_additive=True,
            )
        )
        assert cfg is not None
        assert cfg.enabled is True

    def test_structure_generation_does_not_auto_enable(self):
        for wf in ("crystal_structure", "interface_molecule", "single_molecule_vacuum"):
            cfg = resolve_default_einter_config(EInterPolicyInput(workflow=wf, tier="screening"))
            assert cfg is None, f"{wf} should not auto-enable"

    def test_non_bulk_ff_does_not_auto_enable(self):
        # P1-3: reaxff layered는 CPU rerun 검증이 항상 거부하므로 자동 활성화 안 함.
        cfg = resolve_default_einter_config(
            EInterPolicyInput(
                workflow="layered_structure",
                tier="screening",
                ff_type="reaxff",
                layer_count=3,
            )
        )
        assert cfg is None

    def test_bulk_ff_still_auto_enables(self):
        cfg = resolve_default_einter_config(
            EInterPolicyInput(
                workflow="layered_structure",
                tier="screening",
                ff_type="bulk_ff_gaff2",
                layer_count=3,
            )
        )
        assert cfg is not None and cfg.enabled is True

    def test_flag_off_disables_auto_enable(self, monkeypatch):
        monkeypatch.setattr(policy_mod, "AUTO_ENABLE_PRECISE_EINTER_FOR_LAYERED", False)
        cfg = resolve_default_einter_config(
            EInterPolicyInput(
                workflow="layered_structure",
                tier="screening",
                layer_count=3,
            )
        )
        assert cfg is None
