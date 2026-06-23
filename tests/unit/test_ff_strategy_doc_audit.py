"""Audit test: FF application strategy document exists and contains key policy statements.

Prevents silent drift between documentation and code by verifying that
the canonical mixed-FF strategy document exists and includes the core
policy sections that Phase 1-3 established.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

PROJECT_ROOT = Path(__file__).parent.parent.parent
STRATEGY_DOC = PROJECT_ROOT / "docs" / "architecture" / "ff-application-strategy.md"
SSOT_DOC = PROJECT_ROOT / "docs" / "forcefield_ssot.md"


class TestFFStrategyDocExists:
    """The canonical strategy document must exist and be non-trivial."""

    def test_strategy_doc_exists(self):
        assert STRATEGY_DOC.exists(), (
            f"Missing: {STRATEGY_DOC.relative_to(PROJECT_ROOT)}. "
            "This is the canonical mixed-FF operation strategy document."
        )

    def test_strategy_doc_non_empty(self):
        if not STRATEGY_DOC.exists():
            pytest.skip("strategy doc missing")
        content = STRATEGY_DOC.read_text()
        assert len(content) > 1000, "Strategy doc is suspiciously short"


class TestFFStrategyDocPolicySections:
    """Key policy sections must be present in the strategy document."""

    @pytest.fixture
    def doc_content(self):
        if not STRATEGY_DOC.exists():
            pytest.skip("strategy doc missing")
        return STRATEGY_DOC.read_text()

    def test_material_ff_table(self, doc_content):
        assert "물질군별 FF 사용 원칙" in doc_content

    def test_production_principles(self, doc_content):
        assert "Production 원칙" in doc_content

    def test_fail_closed_policy(self, doc_content):
        assert "fail-closed" in doc_content.lower() or "Fail-closed" in doc_content

    def test_convention_section(self, doc_content):
        assert "Convention" in doc_content or "convention" in doc_content

    def test_mixing_rule_documented(self, doc_content):
        assert "Lorentz-Berthelot" in doc_content or "arithmetic" in doc_content

    def test_fallback_inventory(self, doc_content):
        assert "Fallback 인벤토리" in doc_content or "FORBIDDEN" in doc_content

    def test_compatibility_matrix(self, doc_content):
        assert "호환성 매트릭스" in doc_content

    def test_ionic_policy(self, doc_content):
        assert "Wave 3" in doc_content


class TestForcefieldSSOTReference:
    """forcefield_ssot.md must reference the new strategy document."""

    def test_ssot_doc_references_strategy(self):
        if not SSOT_DOC.exists():
            pytest.skip("forcefield_ssot.md missing")
        content = SSOT_DOC.read_text()
        assert "ff-application-strategy.md" in content, (
            "forcefield_ssot.md should reference the mixed-FF strategy document"
        )
