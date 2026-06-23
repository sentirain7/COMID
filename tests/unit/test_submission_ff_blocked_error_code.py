"""Regression: FF-blocked submission must raise a clean 4xx ContractError.

v01.05.06 — ``submission.py`` referenced ``ErrorCode.VALIDATION_FAILED``,
which does not exist on the ``ErrorCode`` enum, so the FF eligibility gate
raised ``AttributeError`` (→ HTTP 500) instead of the intended
``ContractError(INVALID_REQUEST)`` (→ 4xx) when a blocked species was in
the composition. Existing tests only checked ``collect_binder_ff_issues``
in isolation, never the submission-level conversion, so the bug was hidden.

These tests drive the real submission functions with the FF gate forced to
report a blocked species and assert a proper ``ContractError`` (not
``AttributeError``).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from api.schemas.experiments import MoleculeExperimentRequest
from contracts.errors import ContractError, ErrorCode
from contracts.schemas import MoleculeCountSpec


def _blocked_issue() -> dict:
    return {
        "has_blocked": True,
        "blocked_items": [{"item_id": "BlockedMol", "message": "Generate artifact first"}],
    }


def _request() -> MoleculeExperimentRequest:
    return MoleculeExperimentRequest(
        binder_type="AAA1",
        structure_size="X1",
        aging_state="non_aging",
        molecule_counts=[MoleculeCountSpec(mol_id="BlockedMol", count=1)],
    )


class TestFFBlockedSubmissionErrorCode:
    @pytest.mark.asyncio
    async def test_molecule_submit_raises_contract_error_not_attribute_error(self):
        from features.experiments import submission

        with (
            patch.object(submission, "validate_molecule_request_config", lambda *a, **k: None),
            patch(
                "forcefield.eligibility.collect_binder_ff_issues",
                return_value=_blocked_issue(),
            ),
            patch("api.deps.get_molecule_db"),
            patch("api.deps.get_aging_config"),
        ):
            with pytest.raises(ContractError) as exc_info:
                await submission.submit_molecule_experiment(_request())

        # The bug raised AttributeError before reaching this point.
        assert exc_info.value.code == ErrorCode.INVALID_REQUEST
        assert "FF-blocked" in str(exc_info.value)
        assert exc_info.value.details["ff_blocked_items"][0]["item_id"] == "BlockedMol"

    def test_error_code_member_exists(self):
        # Guards against re-introducing a non-existent ErrorCode member.
        assert hasattr(ErrorCode, "INVALID_REQUEST")
        assert not hasattr(ErrorCode, "VALIDATION_FAILED")
