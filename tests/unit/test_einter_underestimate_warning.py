"""계면 e_inter 과소 경고 테스트 (보완 #2 잔여).

정밀 e_inter(장거리 Coulomb, CPU rerun)가 비활성(opt-out)이면 layered 제출에
'e_inter_long_range_omitted' warn 체크가 붙는지 검증한다.
"""

import sys

sys.path.insert(0, "src")

from features.layered_structures.service import _e_inter_underestimate_check  # noqa: E402


def test_warn_when_interaction_analysis_absent():
    chk = _e_inter_underestimate_check(None)
    assert chk is not None
    assert chk.code == "e_inter_long_range_omitted"
    assert chk.status == "warn"
    assert chk.details["precise_einter_enabled"] is False


def test_warn_when_disabled():
    chk = _e_inter_underestimate_check({"enabled": False})
    assert chk is not None
    assert chk.status == "warn"


def test_no_warn_when_enabled():
    chk = _e_inter_underestimate_check({"enabled": True, "mode": "gpu_then_cpu"})
    assert chk is None


def test_warn_message_mentions_underestimate():
    chk = _e_inter_underestimate_check({})
    assert chk is not None
    assert "UNDERESTIMATED" in chk.message
