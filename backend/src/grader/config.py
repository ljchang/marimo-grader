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
    auth_mode: Literal["saml", "dev", "disabled"] = "dev"
    saml_sp_entity_id: str | None = None
    # Dartmouth moved from Apero CAS to Microsoft EntraID in 2026. Values below
    # are the EntraID tenant's, from the IdP metadata Dartmouth ITC publishes at
    # https://dartmouth.github.io/dartmouth-idp-metadata/metadata.xml
    # (the logout endpoint did not change in the move).
    saml_idp_entity_id: str = "https://sts.windows.net/995b0936-48d6-40e5-a31e-bf689ec9446f/"
    saml_idp_sso_url: str = (
        "https://login.microsoftonline.com/995b0936-48d6-40e5-a31e-bf689ec9446f/saml2"
    )
    saml_idp_logout_url: str = "https://logout.dartmouth.edu"
    saml_idp_cert: str | None = None  # PEM or base64 body
    saml_sp_cert: str | None = None
    saml_sp_key: str | None = None
    saml_clock_skew_seconds: int = 120

    # Email sign-in links. A break-glass sign-in path for when the IdP is not
    # available (before SAML approval, or if it goes down mid-term): the student
    # asks for a link at their campus address and the link opens a session.
    # Off by default, and meant to be turned off again once SSO works -- it is
    # weaker than SAML + Duo, since it proves only control of a mailbox.
    email_login_enabled: bool = False
    email_login_ttl_seconds: int = 7 * 24 * 3600
    # Only addresses at this domain are accepted; the local part is the NetID,
    # matching how roster.py derives a NetID from a Canvas "SIS Login ID".
    email_login_domain: str = "dartmouth.edu"
    email_login_max_per_day: int = 5
    email_login_min_interval_seconds: int = 300

    # Outbound mail. "smtp" talks to any relay (Amazon SES via its SMTP
    # interface); "console" logs the message; "memory" collects it for tests.
    mail_transport: Literal["smtp", "console", "memory"] = "console"
    mail_from: str = "grader@example.test"
    mail_reply_to: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True

    # CORS origins allowed to run the notebook widget.
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:2718",
            "http://127.0.0.1:2718",
            "https://molab.marimo.io",
            "https://dartbrains.org",
        ]
    )
    # MoLab serves the running notebook from a nested iframe on a per-session
    # subdomain of molab.run (e.g. sb-fb0578637b21faaa-session.sb.molab.run),
    # not from molab.marimo.io. The sandbox id is different every session, so no
    # fixed list can cover it and the widget's fetch is blocked without this.
    # Safe to match broadly here: allow_credentials is False, so no cookie ever
    # crosses origins, and every route the widget calls is Bearer-authenticated
    # with a token the student has to approve in a first-party tab.
    cors_origin_regex: str | None = r"^https://[A-Za-z0-9.-]+\.molab\.run$"

    @property
    def cors_regex(self) -> str | None:
        """Origin regex for CORS: the configured one, plus localhost off-prod."""
        patterns = [self.cors_origin_regex] if self.cors_origin_regex else []
        if self.env != "prod":
            patterns.append(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")
        return "|".join(f"(?:{p})" for p in patterns) or None

    artifact_dir: str = "./data/artifacts"
    max_notebook_bytes: int = 2 * 1024 * 1024
    max_outputs_bytes: int = 8 * 1024 * 1024

    # Storage broker (docs/storage-architecture.md). Off until every value is
    # set. Two Cloudflare credentials: the R2 API token's S3 key pair is the
    # *parent* every student credential derives from (bucket-scoped, never
    # leaves this box); the account API token is what may call the mint
    # endpoint and needs the account-wide "Workers R2 Storage: Edit"
    # permission -- the bucket-scoped variant is refused (§5.4).
    storage_enabled: bool = False
    cf_account_id: str | None = None
    cf_api_token: str | None = None
    r2_endpoint: str | None = None  # https://<account>.r2.cloudflarestorage.com
    r2_bucket: str = "dartbrains"
    r2_parent_access_key_id: str | None = None
    r2_parent_secret_access_key: str | None = None
    # Short enough that pulling an assignment or dropping a student bites
    # within the hour; long enough that a lab session never expires mid-file.
    storage_credential_ttl_seconds: int = 3600
    storage_presign_max_seconds: int = 3600
    # HMAC key behind the opaque per-student prefix ids. Rotating it moves every
    # student to a fresh, empty prefix -- do that only between terms.
    storage_uid_secret: str | None = None

    @model_validator(mode="after")
    def _storage_needs_every_value(self) -> Settings:
        if not self.storage_enabled:
            return self
        missing = [
            "GRADER_" + name.upper()
            for name in (
                "cf_account_id",
                "cf_api_token",
                "r2_endpoint",
                "r2_parent_access_key_id",
                "r2_parent_secret_access_key",
                "storage_uid_secret",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise RuntimeError("GRADER_STORAGE_ENABLED=true requires " + ", ".join(missing))
        return self

    @model_validator(mode="after")
    def _email_login_needs_a_transport(self) -> Settings:
        """A sign-in link nobody receives is worse than no button at all."""
        if self.email_login_enabled and self.mail_transport == "smtp" and not self.smtp_host:
            raise RuntimeError(
                "GRADER_EMAIL_LOGIN_ENABLED=true with GRADER_MAIL_TRANSPORT=smtp "
                "requires GRADER_SMTP_HOST"
            )
        return self

    @model_validator(mode="after")
    def _prod_requires_secrets(self) -> Settings:
        if self.env == "prod":
            missing = []
            if self.session_secret.startswith("dev-only"):
                missing.append("GRADER_SESSION_SECRET")
            if not self.jwt_private_key_pem:
                missing.append("GRADER_JWT_PRIVATE_KEY_PEM")
            if self.auth_mode == "dev":
                missing.append("GRADER_AUTH_MODE=saml (or disabled)")
            for name in ("saml_sp_entity_id", "saml_idp_cert", "saml_sp_cert", "saml_sp_key"):
                if self.auth_mode == "saml" and not getattr(self, name):
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
