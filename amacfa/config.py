"""Typed runtime settings. Secrets never enter workflow state."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEMO_ANALYST = "amacfa-demo-analyst"
DEMO_REVIEWER = "amacfa-demo-reviewer"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AMACFA_", env_file=".env", extra="ignore")

    demo_mode: bool = True
    analyst_token: SecretStr = SecretStr(DEMO_ANALYST)
    reviewer_token: SecretStr = SecretStr(DEMO_REVIEWER)
    state_dir: Path = Path(".amacfa")
    max_upload_bytes: int = Field(default=1_048_576, ge=1024, le=5_242_880)
    max_rows: int = Field(default=1000, ge=1, le=3000)
    vector_backend: Literal["local", "chroma"] = "local"
    graph_backend: Literal["local", "neo4j"] = "local"
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr | None = None
    neo4j_database: str = "neo4j"
    llm_backend: Literal["offline", "openai", "anthropic"] = "offline"
    llm_model: str | None = None
    llm_timeout_seconds: float = Field(default=15, ge=1, le=60)
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

    @model_validator(mode="after")
    def validate_configuration(self) -> "Settings":
        tokens = [self.analyst_token.get_secret_value(), self.reviewer_token.get_secret_value()]
        if tokens[0] == tokens[1] or any(
            not token
            or not token.isascii()
            or not token.isprintable()
            or any(character.isspace() for character in token)
            for token in tokens
        ):
            raise ValueError("Analyst and reviewer need distinct, printable ASCII bearer tokens.")
        if not self.demo_mode and any(
            token in {DEMO_ANALYST, DEMO_REVIEWER} or len(token) < 32 for token in tokens
        ):
            raise ValueError("Set two independent bearer tokens of at least 32 characters.")
        if self.graph_backend == "neo4j" and (
            self.neo4j_password is None or not self.neo4j_password.get_secret_value()
        ):
            raise ValueError("Set AMACFA_NEO4J_PASSWORD for the Neo4j backend.")
        for provider, credential in (
            ("openai", self.openai_api_key),
            ("anthropic", self.anthropic_api_key),
        ):
            if self.llm_backend == provider and (
                credential is None or not credential.get_secret_value()
            ):
                raise ValueError(f"Set {provider.upper()}_API_KEY for this LLM backend.")
        return self
