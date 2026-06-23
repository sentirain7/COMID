"""Tests for ContractError -> HTTP response mapping."""

import pytest

from api.application import _status_code_for_contract_error, contract_error_handler
from contracts.errors import ContractError, ErrorCode


def test_status_code_mapping() -> None:
    assert _status_code_for_contract_error("E1000") == 400
    assert _status_code_for_contract_error("E7001") == 404
    assert _status_code_for_contract_error("E9505") == 404
    assert _status_code_for_contract_error("E8003") == 503
    assert _status_code_for_contract_error("E10004") == 500
    assert _status_code_for_contract_error("E6000") == 500


@pytest.mark.asyncio
async def test_contract_error_handler_returns_structured_json() -> None:
    exc = ContractError(ErrorCode.DATABASE_ERROR, "db failed", {"foo": "bar"})
    response = await contract_error_handler(None, exc)
    assert response.status_code == 500
    assert response.body is not None
    assert b'"code":"E7000"' in response.body
    assert b'"message":"db failed"' in response.body
    assert b'"detail":"db failed"' in response.body
