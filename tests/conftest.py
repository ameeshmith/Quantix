"""Pytest configuration and global test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def set_test_environment(monkeypatch):
    """Ensure safe, compliant environment defaults for all unit tests."""
    monkeypatch.setenv("EDGAR_USER_AGENT", "QuantixTest test@example.com")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("MCP_API_KEY", "test-secret-token")
    monkeypatch.setenv("DB_PATH", "test_quantix.db")
    # Ensure offline test mode for LLM unless specifically mocked
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
