"""Phase 9: Single Molecule submission regression tests.

Tests cover the fail-closed blocking logic in submit_single_molecule_batch():
- Blocked molecules (is_submittable=false) → all temperatures fail immediately
- Non-existent molecules → all temperatures fail
- Response includes resolved_ff_hint / resolved_ff_display_label
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from features.experiments.single_molecule import (  # noqa: E402
    _make_single_molecule_exp_id,
    submit_single_molecule_batch,
)


def _make_request(mol_id="SiO2", temps=None, seed=20260101, force=False):
    return SimpleNamespace(
        selected_mol_id=mol_id,
        temperatures_k=temps or [298.0, 313.0, 333.0],
        seed=seed,
        force_recompute=force,
    )


class TestSingleMoleculeExpId:
    """Single-molecule IDs should carry the temperature in the visible token."""

    def test_exp_id_includes_temperature_token(self):
        exp_id = _make_single_molecule_exp_id(
            mol_id="U-AS-Thio-0293",
            temperature_k=293.0,
            ff_type="bulk_ff_gaff2",
            atom_count=42,
            seed=20260101,
        )

        assert exp_id.startswith("SM_U-AS-Thio-0293_293K_")
        assert len(exp_id.rsplit("_", 1)[1]) == 6

    def test_exp_id_hash_still_changes_by_temperature(self):
        exp_id_293 = _make_single_molecule_exp_id(
            mol_id="U-AS-Thio-0293",
            temperature_k=293.0,
            ff_type="bulk_ff_gaff2",
            atom_count=42,
            seed=20260101,
        )
        exp_id_313 = _make_single_molecule_exp_id(
            mol_id="U-AS-Thio-0293",
            temperature_k=313.0,
            ff_type="bulk_ff_gaff2",
            atom_count=42,
            seed=20260101,
        )

        assert exp_id_293.startswith("SM_U-AS-Thio-0293_293K_")
        assert exp_id_313.startswith("SM_U-AS-Thio-0293_313K_")
        assert exp_id_293 != exp_id_313


class TestSubmitBlockedMolecule:
    """Blocked molecules should be rejected immediately by the server."""

    @pytest.mark.asyncio
    async def test_blocked_molecule_returns_failed(self):
        """All temperatures fail with blocked_reason when is_submittable=false."""
        with patch(
            "features.molecules.catalog.resolve_ff_hint",
            return_value={
                "ff_hint": "interface_profile",
                "ff_display_label": "INTERFACE (blocked)",
                "parameterization_mode": "inorganic_profile",
                "submit_ff_type": "bulk_ff_gaff2",
                "is_submittable": False,
                "blocked_reason": "Blocked placeholder — parameterization not ready",
            },
        ):
            request = _make_request(mol_id="NanoClay")
            result = await submit_single_molecule_batch(request)

        assert result["mol_id"] == "NanoClay"
        assert result["total"] == 3
        assert result["submitted"] == 0
        assert result["failed"] == 3
        assert result["skipped_existing"] == 0
        assert all(item["status"] == "failed" for item in result["items"])
        assert all("Blocked placeholder" in item["error"] for item in result["items"])
        assert result["resolved_ff_hint"] == "interface_profile"
        assert result["resolved_ff_display_label"] == "INTERFACE (blocked)"

    @pytest.mark.asyncio
    async def test_inorganic_missing_mode_blocked(self):
        with patch(
            "features.molecules.catalog.resolve_ff_hint",
            return_value={
                "ff_hint": "gaff2",
                "ff_display_label": "GAFF2",
                "parameterization_mode": None,
                "submit_ff_type": "bulk_ff_gaff2",
                "is_submittable": False,
                "blocked_reason": "Inorganic additive missing parameterization mode",
            },
        ):
            request = _make_request(mol_id="MysteryRock", temps=[298.0])
            result = await submit_single_molecule_batch(request)

        assert result["failed"] == 1
        assert "missing parameterization mode" in result["items"][0]["error"]


class TestSubmitNonExistentMolecule:
    """Molecules not in MoleculeDB should fail with explicit error."""

    @pytest.mark.asyncio
    async def test_unknown_mol_id_returns_failed(self):
        mock_db = MagicMock()
        mock_db.get.return_value = None  # mol_id not found in MoleculeDB

        with (
            patch(
                "features.molecules.catalog.resolve_ff_hint",
                return_value={
                    "ff_hint": "gaff2",
                    "ff_display_label": "GAFF2",
                    "parameterization_mode": None,
                    "submit_ff_type": "bulk_ff_gaff2",
                    "is_submittable": True,
                    "blocked_reason": None,
                },
            ),
            patch("api.deps.get_molecule_db", return_value=mock_db),
        ):
            request = _make_request(mol_id="DoesNotExist", temps=[298.0, 313.0])
            result = await submit_single_molecule_batch(request)

        assert result["failed"] == 2
        assert result["submitted"] == 0
        assert all("not found in MoleculeDB" in item["error"] for item in result["items"])
        # Regression: response must include resolved_ff_hint fields even in this branch
        # (was missing → caused ResponseValidationError "Field required")
        assert "resolved_ff_hint" in result
        assert "resolved_ff_display_label" in result


class TestSchemaValidation:
    """Verify SingleMoleculeBatchRequest validates input correctly."""

    def test_empty_mol_id_rejected(self):
        from pydantic import ValidationError

        from api.schemas.experiments import SingleMoleculeBatchRequest

        with pytest.raises(ValidationError):
            SingleMoleculeBatchRequest(selected_mol_id="", temperatures_k=[298.0])

    def test_valid_request_accepted(self):
        from api.schemas.experiments import SingleMoleculeBatchRequest

        req = SingleMoleculeBatchRequest(
            selected_mol_id="U-AS-Thio-0293",
            temperatures_k=[293.0],
            seed=20260101,
            force_recompute=False,
        )
        assert req.selected_mol_id == "U-AS-Thio-0293"
        assert req.temperatures_k == [293.0]

    def test_response_validates_with_all_branch_outputs(self):
        """All known return shapes from submit_single_molecule_batch must satisfy
        SingleMoleculeBatchResponse schema."""
        from api.schemas.experiments import SingleMoleculeBatchResponse

        # Branch 1: blocked
        blocked = {
            "mol_id": "NanoClay",
            "total": 1,
            "submitted": 0,
            "skipped_existing": 0,
            "failed": 1,
            "items": [
                {"temperature_K": 298.0, "status": "failed", "exp_id": None, "error": "blocked"}
            ],
            "resolved_ff_hint": "interface_profile",
            "resolved_ff_display_label": "INTERFACE (blocked)",
        }
        SingleMoleculeBatchResponse(**blocked)  # should not raise

        # Branch 2: not found in MoleculeDB
        notfound = {
            "mol_id": "Unknown",
            "total": 1,
            "submitted": 0,
            "skipped_existing": 0,
            "failed": 1,
            "items": [
                {"temperature_K": 298.0, "status": "failed", "exp_id": None, "error": "not found"}
            ],
            "resolved_ff_hint": "gaff2",
            "resolved_ff_display_label": "GAFF2",
        }
        SingleMoleculeBatchResponse(**notfound)  # should not raise

        # Branch 3: success
        success = {
            "mol_id": "U-AS-Thio-0293",
            "total": 1,
            "submitted": 1,
            "skipped_existing": 0,
            "failed": 0,
            "items": [
                {
                    "temperature_K": 293.0,
                    "status": "submitted",
                    "exp_id": "exp_001",
                    "error": None,
                }
            ],
            "resolved_ff_hint": "gaff2",
            "resolved_ff_display_label": "GAFF2",
        }
        SingleMoleculeBatchResponse(**success)  # should not raise


class TestResponseSchema:
    """Verify response always includes the resolved FF fields."""

    @pytest.mark.asyncio
    async def test_response_includes_resolved_ff_fields_on_block(self):
        """Even on rejection, response carries resolved FF metadata."""
        with patch(
            "features.molecules.catalog.resolve_ff_hint",
            return_value={
                "ff_hint": "gaff2",
                "ff_display_label": "GAFF2",
                "parameterization_mode": None,
                "submit_ff_type": "bulk_ff_gaff2",
                "is_submittable": False,
                "blocked_reason": "test reason",
            },
        ):
            request = _make_request(mol_id="X", temps=[298.0])
            result = await submit_single_molecule_batch(request)

        assert "resolved_ff_hint" in result
        assert "resolved_ff_display_label" in result
        assert result["resolved_ff_hint"] == "gaff2"
        assert result["resolved_ff_display_label"] == "GAFF2"
