"""Unit tests for the per-molecule progress wrapper in topology_assembly.

Covers the small helper ``_make_mol_progress_wrapper`` used by
:func:`generate_full_topology` to prepend ``[i/N mol_id] `` to FF sub-phase
labels before forwarding them to the pipeline's progress callback.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from builder.topology_assembly import _make_mol_progress_wrapper  # noqa: E402


class TestMakeMolProgressWrapper:
    def test_none_emit_returns_none(self):
        """No upstream progress → no wrapper needed."""
        assert _make_mol_progress_wrapper("[1/1 X] ", None) is None

    def test_prefix_prepended_to_label(self):
        captured: list[tuple[str, str]] = []

        def _emit(code, label):
            captured.append((code, label))

        wrapper = _make_mol_progress_wrapper("[3/12 SA-Squalane] ", _emit)
        assert wrapper is not None
        wrapper("artifact_antechamber", "부분전하 계산 (antechamber AM1-BCC)")

        assert captured == [
            (
                "artifact_antechamber",
                "[3/12 SA-Squalane] 부분전하 계산 (antechamber AM1-BCC)",
            )
        ]

    def test_swallows_emit_exceptions(self):
        """Callback errors must not break the build pipeline."""

        def _emit(code, label):
            raise RuntimeError("downstream telemetry failure")

        wrapper = _make_mol_progress_wrapper("[1/1 Mol] ", _emit)
        assert wrapper is not None
        # Should not raise.
        wrapper("artifact_parmchk2", "본딩 파라미터 보완 (parmchk2)")

    def test_code_passed_through_unchanged(self):
        """Only label receives the prefix — code must remain untouched."""
        mock = MagicMock()
        wrapper = _make_mol_progress_wrapper("[2/5 Lignin] ", mock)
        assert wrapper is not None
        wrapper("artifact_parmed", "LJ/bonded 파라미터 추출 (parmed)")

        mock.assert_called_once_with(
            "artifact_parmed", "[2/5 Lignin] LJ/bonded 파라미터 추출 (parmed)"
        )
