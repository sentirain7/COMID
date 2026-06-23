"""Unit tests for typing/charge precompute endpoint logic.

Phase 6: legacy RDKit assigner patches removed. Organic routing now goes
through organic_typing_executor.assign_organic (curated artifact path).
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.schemas import TypingChargePrecomputeRequest
from contracts.errors import ContractError, ErrorCode

HAS_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None
pytestmark = pytest.mark.skipif(not HAS_SQLALCHEMY, reason="sqlalchemy not installed")


def _install_fastapi_stub() -> None:
    """Install a minimal fastapi stub for environments without FastAPI."""
    if "fastapi" in sys.modules:
        return

    class _Router:
        def _decorator(self, *_args, **_kwargs):
            def _wrap(func):
                return func

            return _wrap

        get = _decorator
        post = _decorator
        delete = _decorator

    fastapi_stub = types.ModuleType("fastapi")
    fastapi_stub.APIRouter = lambda *args, **kwargs: _Router()
    sys.modules["fastapi"] = fastapi_stub

    # Sub-modules that features.experiments.router imports
    responses_stub = types.ModuleType("fastapi.responses")
    responses_stub.Response = type("Response", (), {})
    sys.modules["fastapi.responses"] = responses_stub


def _mock_settings(enabled: bool = True):
    return SimpleNamespace(
        typing_charge=SimpleNamespace(
            enabled=enabled,
            charge_model_primary="am1bcc",
            charge_model_fallback="am1bcc",
            total_charge_tolerance=0.2,
        )
    )


class _FakeDB:
    def __init__(
        self,
        mol_files: dict[str, Path],
        additive_defs: dict[str, dict] | None = None,
        ff_assignments: dict[str, dict] | None = None,
    ) -> None:
        self._mol_files = mol_files
        self._additive_defs = additive_defs or {}
        self._ff_assignments = ff_assignments or {}
        self._aging_config_path = None

    def get_structure_file(self, mol_id: str, fmt: str):
        if fmt != "mol":
            return None
        return self._mol_files.get(mol_id)

    def get_structure_file_aging(self, _mol_id: str, _config_path):
        return None

    def parse_mol_topology(self, mol_path: Path, mol_id: str):
        if not mol_path.exists():
            return None
        return SimpleNamespace(
            mol_id=mol_id,
            atoms=[
                SimpleNamespace(index=1, element="C", ff_type="", charge=0.0, charge_defined=False),
                SimpleNamespace(index=2, element="H", ff_type="", charge=0.0, charge_defined=False),
            ],
            bonds=[],
        )

    def get_additive_definition(self, mol_id: str):
        return self._additive_defs.get(mol_id)

    def get_additives_load_error(self):
        return None

    def get_ff_assignment(self, mol_id: str):
        """Return pre-seeded ff_assignment or None."""
        entry = self._ff_assignments.get(mol_id)
        return dict(entry) if entry else None

    def get_ff_assignment_load_error(self):
        return None


class _FakeInorganicResult(SimpleNamespace):
    pass


class _FakeInorganicCallTracker:
    """Tracks calls to assign_inorganic_with_cache stand-in."""

    def __init__(self, cache_hit: bool = False) -> None:
        self.calls: list[str] = []
        self.cache_hit = cache_hit

    def __call__(self, *, topology, mol_file, additive_def, service=None, cache=None):
        self.calls.append(topology.mol_id)
        return _FakeInorganicResult(
            cache_hit=self.cache_hit,
            profile_id="silica_hydroxylated_v1",
            profile_version="1.0",
            total_charge=0.0,
            atom_type_coeffs={},
            bond_type_coeffs={},
            angle_type_coeffs={},
            dihedral_policy="strict",
        )


def _make_routing_request(mol_ids, additives=None):
    """Build a TypingChargePrecomputeRequest from raw lists."""
    additives = additives or []
    return TypingChargePrecomputeRequest(
        binder_type="custom",
        structure_size="X1",
        aging_state="non_aging",
        ff_type="bulk_ff_gaff2",
        molecule_counts=[
            {"mol_id": m, "count": 1} for m in mol_ids if m not in {a["mol_id"] for a in additives}
        ],
        additives=additives,
    )


class TestPrecomputeRouting:
    """Routing regression: inorganic vs blocked."""

    def test_active_inorganic_uses_inorganic_executor_only(self, tmp_path) -> None:
        _install_fastapi_stub()
        from features.experiments.submission import precompute_typing_charge

        mol_file = tmp_path / "SiO2.mol"
        mol_file.write_text("SiO2")
        inorganic_tracker = _FakeInorganicCallTracker()

        fake_db = _FakeDB(
            {"SiO2": mol_file},
            additive_defs={
                "SiO2": {
                    "category": "inorganic",
                    "parameterization": {
                        "mode": "inorganic_profile",
                        "profile_id": "silica_hydroxylated_v1",
                    },
                }
            },
        )
        request = _make_routing_request(["SiO2"], additives=[{"mol_id": "SiO2", "count": 1}])

        with (
            patch("api.deps.get_molecule_db", return_value=fake_db),
            patch("api.deps.get_aging_config", return_value={}),
            patch("features.experiments.submission.validate_molecule_request_config"),
            patch("config.settings.get_settings", return_value=_mock_settings(enabled=True)),
            patch(
                "forcefield.inorganic_parameter_service.InorganicParameterService",
                lambda *a, **k: SimpleNamespace(),
            ),
            patch(
                "forcefield.inorganic_executor.InorganicTypingCache",
                lambda *a, **k: SimpleNamespace(),
            ),
            patch(
                "forcefield.inorganic_executor.assign_inorganic_with_cache",
                inorganic_tracker,
            ),
        ):
            result = asyncio.run(precompute_typing_charge(request))

        assert inorganic_tracker.calls == ["SiO2"]
        assert result.failed == 0
        assert result.computed == 1
        assert result.details[0].charge_model == "clayff_interface"

    def test_inorganic_cache_hit_reports_cached(self, tmp_path) -> None:
        _install_fastapi_stub()
        from features.experiments.submission import precompute_typing_charge

        mol_file = tmp_path / "SiO2.mol"
        mol_file.write_text("SiO2")
        inorganic_tracker = _FakeInorganicCallTracker(cache_hit=True)

        fake_db = _FakeDB(
            {"SiO2": mol_file},
            additive_defs={
                "SiO2": {
                    "category": "inorganic",
                    "parameterization": {
                        "mode": "inorganic_profile",
                        "profile_id": "silica_hydroxylated_v1",
                    },
                }
            },
        )
        request = _make_routing_request(["SiO2"], additives=[{"mol_id": "SiO2", "count": 1}])

        with (
            patch("api.deps.get_molecule_db", return_value=fake_db),
            patch("api.deps.get_aging_config", return_value={}),
            patch("features.experiments.submission.validate_molecule_request_config"),
            patch("config.settings.get_settings", return_value=_mock_settings(enabled=True)),
            patch(
                "forcefield.inorganic_parameter_service.InorganicParameterService",
                lambda *a, **k: SimpleNamespace(),
            ),
            patch(
                "forcefield.inorganic_executor.InorganicTypingCache",
                lambda *a, **k: SimpleNamespace(),
            ),
            patch(
                "forcefield.inorganic_executor.assign_inorganic_with_cache",
                inorganic_tracker,
            ),
        ):
            result = asyncio.run(precompute_typing_charge(request))

        assert result.cached == 1
        assert result.computed == 0
        assert result.details[0].status == "cached"
        assert result.details[0].charge_model == "clayff_interface"

    def test_blocked_placeholder_returns_failed_no_assigner_calls(self, tmp_path) -> None:
        _install_fastapi_stub()
        from features.experiments.submission import precompute_typing_charge

        mol_file = tmp_path / "NanoClay.mol"
        mol_file.write_text("NanoClay")
        inorganic_tracker = _FakeInorganicCallTracker()

        fake_db = _FakeDB(
            {"NanoClay": mol_file},
            additive_defs={
                "NanoClay": {
                    "category": "inorganic",
                    "parameterization": {
                        "mode": "inorganic_profile",
                        "status": "blocked_placeholder",
                        "profile_id": "montmorillonite_v1",
                    },
                }
            },
        )
        request = _make_routing_request(
            ["NanoClay"], additives=[{"mol_id": "NanoClay", "count": 1}]
        )

        with (
            patch("api.deps.get_molecule_db", return_value=fake_db),
            patch("api.deps.get_aging_config", return_value={}),
            patch("features.experiments.submission.validate_molecule_request_config"),
            patch("config.settings.get_settings", return_value=_mock_settings(enabled=True)),
            patch(
                "forcefield.inorganic_executor.assign_inorganic_with_cache",
                inorganic_tracker,
            ),
        ):
            result = asyncio.run(precompute_typing_charge(request))

        assert inorganic_tracker.calls == []
        assert result.failed == 1
        assert result.details[0].status == "failed"
        assert "blocked_placeholder" in (result.details[0].message or "")

    def test_inorganic_missing_mode_returns_failed(self, tmp_path) -> None:
        _install_fastapi_stub()
        from features.experiments.submission import precompute_typing_charge

        mol_file = tmp_path / "MysteryRock.mol"
        mol_file.write_text("MysteryRock")
        inorganic_tracker = _FakeInorganicCallTracker()

        fake_db = _FakeDB(
            {"MysteryRock": mol_file},
            additive_defs={"MysteryRock": {"category": "inorganic", "parameterization": {}}},
        )
        request = _make_routing_request(
            ["MysteryRock"], additives=[{"mol_id": "MysteryRock", "count": 1}]
        )

        with (
            patch("api.deps.get_molecule_db", return_value=fake_db),
            patch("api.deps.get_aging_config", return_value={}),
            patch("features.experiments.submission.validate_molecule_request_config"),
            patch("config.settings.get_settings", return_value=_mock_settings(enabled=True)),
            patch(
                "forcefield.inorganic_executor.assign_inorganic_with_cache",
                inorganic_tracker,
            ),
        ):
            result = asyncio.run(precompute_typing_charge(request))

        assert inorganic_tracker.calls == []
        assert result.failed == 1
        assert "missing parameterization.mode" in (result.details[0].message or "")


def test_precompute_typing_charge_rejects_when_typing_disabled(tmp_path) -> None:
    """Precompute should fail fast when typing/charge feature is disabled."""
    _install_fastapi_stub()
    from features.experiments.submission import precompute_typing_charge

    mol_a = tmp_path / "A.mol"
    mol_a.write_text("A")
    fake_db = _FakeDB({"A": mol_a})
    request = TypingChargePrecomputeRequest(
        binder_type="custom",
        structure_size="X1",
        aging_state="non_aging",
        ff_type="bulk_ff_gaff2",
        molecule_counts=[{"mol_id": "A", "count": 1}],
    )

    with (
        patch("api.deps.get_molecule_db", return_value=fake_db),
        patch("api.deps.get_aging_config", return_value={}),
        patch("features.experiments.submission.validate_molecule_request_config"),
        patch("config.settings.get_settings", return_value=_mock_settings(enabled=False)),
    ):
        with pytest.raises(ContractError) as exc_info:
            asyncio.run(precompute_typing_charge(request))

    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


def test_inorganic_additive_in_molecule_counts_not_additives(tmp_path) -> None:
    """SiO2 sent via molecule_counts (single molecule screen) must still
    resolve its additive_def from MoleculeDB so the inorganic executor
    gets parameterization.profile_id.
    """
    _install_fastapi_stub()
    from features.experiments.submission import precompute_typing_charge

    mol_file = tmp_path / "SiO2.mol"
    mol_file.write_text("SiO2")
    inorganic_tracker = _FakeInorganicCallTracker()

    fake_db = _FakeDB(
        {"SiO2": mol_file},
        additive_defs={
            "SiO2": {
                "category": "inorganic",
                "parameterization": {
                    "mode": "inorganic_profile",
                    "profile_id": "silica_hydroxylated_v1",
                    "status": "active",
                },
            }
        },
        ff_assignments={
            "SiO2": {
                "route": "inorganic_profile",
                "status": "active",
                "source_id": "silica_hydroxylated_v1",
                "formal_charge": 0,
                "canonical_smiles": None,
            }
        },
    )

    # SiO2 is in molecule_counts, NOT in additives
    request = TypingChargePrecomputeRequest(
        binder_type="custom",
        structure_size="X1",
        aging_state="non_aging",
        ff_type="bulk_ff_gaff2",
        molecule_counts=[{"mol_id": "SiO2", "count": 1}],
        additives=None,
    )

    with (
        patch("api.deps.get_molecule_db", return_value=fake_db),
        patch("api.deps.get_aging_config", return_value={}),
        patch("features.experiments.submission.validate_molecule_request_config"),
        patch("config.settings.get_settings", return_value=_mock_settings(enabled=True)),
        patch(
            "forcefield.inorganic_parameter_service.InorganicParameterService",
            lambda *a, **k: SimpleNamespace(),
        ),
        patch(
            "forcefield.inorganic_executor.InorganicTypingCache",
            lambda *a, **k: SimpleNamespace(),
        ),
        patch(
            "forcefield.inorganic_executor.assign_inorganic_with_cache",
            inorganic_tracker,
        ),
    ):
        result = asyncio.run(precompute_typing_charge(request))

    # The inorganic executor must have been called (not the organic one).
    assert inorganic_tracker.calls == ["SiO2"], (
        "SiO2 in molecule_counts must still route to the inorganic "
        f"executor; got calls={inorganic_tracker.calls}"
    )
    assert result.failed == 0, f"SiO2 precompute should succeed; details={result.details}"
    assert result.computed == 1 or result.cached == 1
    assert result.details[0].charge_model == "clayff_interface"
