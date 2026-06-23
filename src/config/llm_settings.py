"""LLM provider settings."""

from pydantic import Field
from pydantic_settings import BaseSettings


class LLMSettings(BaseSettings):
    """LLM-specific settings."""

    provider: str = Field(default="mock", description="LLM provider: mock|anthropic|openai")
    anthropic_api_key: str | None = Field(default=None)
    anthropic_model: str = Field(default="claude-3-5-sonnet-latest")
    openai_api_key: str | None = Field(default=None)
    openai_model: str = Field(default="gpt-4o-mini")
    temperature: float = Field(default=0.4)
    max_tokens: int = Field(default=2048)

    class Config:
        env_prefix = "LLM_"
