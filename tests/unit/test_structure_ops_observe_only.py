"""v00.99.72 — structure_ops preview must call probe with observe_only=True.

Regression guard for the "Lignin preview blocks the thread pool" incident.
If anyone removes the ``observe_only=True`` kwarg on the preview path,
this test fails loudly before the change reaches the server.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from features.molecules import structure_ops  # noqa: E402


def _topology():
    return SimpleNamespace(
        atoms=[
            SimpleNamespace(
                element="C",
                charge=0.0,
                charge_defined=False,
            )
        ],
        bonds=[],
    )


def test_preview_analyze_topology_passes_observe_only_true(tmp_path):
    mol_path = tmp_path / "x.mol"
    mol_path.write_text("dummy")

    mock_db = MagicMock()
    mock_db.get_ff_assignment.return_value = {
        "route": "organic_curated_artifact",
        "status": "active",
        "source_id": "X",
    }
    mock_db.get_additive_definition.return_value = None

    with (
        patch("api.deps.get_molecule_db", return_value=mock_db),
        patch(
            "builder.topology_helpers.probe_single_component_generation_support",
            return_value=(True, None),
        ) as probe_mock,
    ):
        structure_ops._analyze_topology(_topology(), mol_path, "X")

    probe_mock.assert_called_once()
    kwargs = probe_mock.call_args.kwargs
    assert kwargs.get("observe_only") is True, (
        "preview must call probe with observe_only=True to avoid blocking "
        "the thread pool on AM1-BCC for large molecules like Lignin"
    )
