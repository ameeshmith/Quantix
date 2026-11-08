"""Configuration management using Pydantic Settings."""

from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from quantix.exceptions import ConfigurationError


class Settings(BaseSettings):
    """Quantix environment settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # SEC EDGAR Requirements
    edgar_user_agent: str = Field(
        default="",
        description="User-Agent for SEC EDGAR requests. Format: 'AppName contact@example.com'",
    )
    sec_verify_ssl: bool = Field(
        default=True,
        description="Whether to verify SSL certificates for SEC EDGAR requests",
    )

    # SQLite Database Path
    db_path: str = Field(
        default="quantix.db",
        description="Path to SQLite database file",
    )

    # MCP Transport & Auth
    mcp_transport: Literal["stdio", "streamable-http"] = Field(
        default="stdio",
        description="MCP server transport: 'stdio' for desktop or 'streamable-http' for remote",
    )
    mcp_host: str = Field(default="0.0.0.0", description="Host to bind for HTTP transport")
    mcp_port: int = Field(default=8000, description="Port to bind for HTTP transport")
    mcp_api_key: Optional[str] = Field(
        default=None,
        description="Bearer token required for HTTP transport authentication",
    )

    # LLM Settings
    llm_provider: str = Field(
        default="groq",
        description="LLM provider: 'groq', 'openai', 'anthropic', or custom openai-compatible",
    )
    llm_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Model name to use with the selected provider",
    )
    llm_api_key: Optional[str] = Field(
        default=None,
        description="Generic API key for LLM provider if specific keys not provided",
    )
    groq_api_key: Optional[str] = Field(default=None, description="Groq API key")
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key")
    anthropic_api_key: Optional[str] = Field(default=None, description="Anthropic API key")
    llm_base_url: Optional[str] = Field(
        default=None,
        description="Base URL for OpenAI-compatible endpoint",
    )

    # Alerts & Telegram
    telegram_bot_token: Optional[str] = Field(
        default=None,
        description="Telegram Bot API token for filing alerts",
    )
    telegram_chat_id: Optional[str] = Field(
        default=None,
        description="Telegram Chat ID for receiving filing alerts",
    )
    alert_schedule: str = Field(
        default="0 8 * * 1-5",
        description="Cron schedule for checking new 8-K filings (default: 8:00 AM Mon-Fri)",
    )

    # Testing & Debugging
    run_live_tests: bool = Field(
        default=False,
        description="Enable live SEC EDGAR network tests when set to True",
    )

    @field_validator("edgar_user_agent")
    @classmethod
    def validate_user_agent(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ConfigurationError(
                "EDGAR_USER_AGENT environment variable is missing. "
                "SEC EDGAR requires a User-Agent header in the form 'AppName contact@example.com'."
            )
        if "@" not in trimmed:
            raise ConfigurationError(
                f"EDGAR_USER_AGENT ('{trimmed}') is invalid: must contain an email address."
            )
        return trimmed

    def get_llm_api_key(self) -> Optional[str]:
        """Resolve the appropriate API key based on provider, ignoring placeholder values."""
        prov = self.llm_provider.lower()
        if prov == "anthropic":
            raw_key = self.anthropic_api_key or self.llm_api_key
        elif prov == "groq":
            raw_key = self.groq_api_key or self.llm_api_key or self.openai_api_key
        else:
            raw_key = self.openai_api_key or self.groq_api_key or self.llm_api_key

        if not raw_key:
            return None

        cleaned = raw_key.strip()
        # Treat unedited template placeholders as unconfigured
        if cleaned.startswith("your_") or "placeholder" in cleaned.lower():
            return None
        return cleaned

    def ensure_db_dir(self) -> None:
        """Ensure parent directory for SQLite database exists."""
        p = Path(self.db_path)
        if p.parent and not p.parent.exists():
            p.parent.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Load settings from environment with error handling."""
    return Settings()
