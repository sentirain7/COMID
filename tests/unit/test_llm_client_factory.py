"""Tests for LLM client factory and shared mock client."""

import pytest

pytest.importorskip("dotenv")

from config.settings import reset_settings
from llm.client_factory import create_llm_client
from llm.mock_client import MockLLMClient


def test_create_llm_client_default_mock(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    reset_settings()
    client = create_llm_client()
    assert isinstance(client, MockLLMClient)


def test_create_llm_client_missing_openai_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_OPENAI_API_KEY", raising=False)
    reset_settings()
    with pytest.raises(RuntimeError):
        create_llm_client()
