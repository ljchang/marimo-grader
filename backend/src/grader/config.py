"""Runtime configuration.

Every secret comes from the environment (or Docker secrets mounted as files
and exported by the entrypoint). In production the service refuses to start
if a required secret is missing, following the fail-closed pattern from
pbs_knowledge's SAML service.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRADER_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"
    database_url: str = "postgresql+psycopg://grader:grader@localhost:5432/grader"

    # Session cookies for the web UI.
    session_secret: str = Field(default="dev-only-session-secret-change-me")
    session_cookie: str = "grader_session"
    session_ttl_seconds: int = 12 * 3600
    cookie_secure: bool = False

    # Notebook tokens (JWT, EdDSA). PEM-encoded Ed25519 private key.
    jwt_private_key_pem: str | None = None
    notebook_token_ttl_seconds: int = 8 * 3600
    device_code_ttl_seconds: int = 600
    device_poll_interval_seconds: int = 3

    # Auth mode: "saml" uses Dartmouth; "dev" enables /auth/dev-login.
    auth_mode: Literal["saml", "dev"] = "dev"
    saml_sp_entity_id: str | None = None
    saml_idp_entity_id: str = "urn:mace:incommon:dartmouth.edu"
    saml_idp_sso_url: str = "https://login.dartmouth.edu/cas/idp/profile/SAML2/POST/SSO"
    saml_idp_logout_url: str = "https://logout.dartmouth.edu"
    saml_idp_cert: str | None = None  # PEM or base64 body
    saml_sp_cert: str | None = None
    saml_sp_key: str | None = None
    saml_clock_skew_seconds: int = 120

    # CORS origins allowed to run the notebook widget.
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:2718",
            "http://127.0.0.1:2718",
            "https://molab.marimo.io",
            "https://dartbrains.org",
        ]
    )

    artifact_dir: str = "./data/artifacts"
    max_notebook_bytes: int = 2 * 1024 * 1024
    max_outputs_bytes: int = 8 * 1024 * 1024

    @model_validator(mode="after")
    def _prod_requires_secrets(self) -> Settings:
        if self.env == "prod":
            missing = []
            if self.session_secret.startswith("dev-only"):
                missing.append("GRADER_SESSION_SECRET")
            if not self.jwt_private_key_pem:
                missing.append("GRADER_JWT_PRIVATE_KEY_PEM")
            if self.auth_mode != "saml":
                missing.append("GRADER_AUTH_MODE=saml")
            for name in ("saml_sp_entity_id", "saml_idp_cert", "saml_sp_cert", "saml_sp_key"):
                if not getattr(self, name):
                    missing.append("GRADER_" + name.upper())
            if not self.cookie_secure:
                missing.append("GRADER_COOKIE_SECURE=true")
            if missing:
                raise RuntimeError(
                    "Refusing to start in prod with missing configuration: " + ", ".join(missing)
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
