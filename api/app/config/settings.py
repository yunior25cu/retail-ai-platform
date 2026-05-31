"""Application settings — single source of truth for all configuration.

Reads from environment variables and/or api/.env (via pydantic-settings).
Never hardcode passwords, keys, or host names in application code.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Runtime environment ───────────────────────────────────────────────────
    environment: str = "development"   # development | production

    # ── Anthropic ─────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # ── Gold DB (SQL Server) ──────────────────────────────────────────────────
    # Required — set via SQL_SERVER, SQL_DATABASE, SQL_USER, SQL_PASSWORD in .env
    sql_server: str = ""
    sql_database: str = ""
    sql_user: str = ""
    sql_password: str = ""
    sql_driver: str = "{ODBC Driver 17 for SQL Server}"
    sql_pool_size: int = 10

    # ── JWT ───────────────────────────────────────────────────────────────────
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    auth_require_jwt: bool = False   # True in prod: disables X-Mock-* header fallback

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_json: bool = False           # True in prod: emits structured JSON

    # ── Rate limits ───────────────────────────────────────────────────────────
    rate_limit_tenant_hour: int = 100
    rate_limit_user_hour: int = 30
    rate_limit_tokens_day: int = 1_000_000

    # ── Conversational memory ─────────────────────────────────────────────────
    memory_turns_per_request: int = 3   # user+assistant pairs loaded per request

    # ── Service-to-service auth ───────────────────────────────────────────────
    service_key: str = ""     # shared secret with ERP proxy; empty = service auth disabled
    service_mode: bool = False  # True = reject all non-service requests (production only)

    # ── JWT auth service (FASE 1) ─────────────────────────────────────────────
    jwt_expire_hours: int = 24         # access token lifetime; overrides jwt_expire_minutes
    bcrypt_rounds: int = 12            # bcrypt cost factor (min 12 in production)
    refresh_token_expire_days: int = 30

    @property
    def odbc_connection_string(self) -> str:
        """ODBC connection string built from individual settings."""
        return (
            f"DRIVER={self.sql_driver};"
            f"SERVER={self.sql_server};"
            f"DATABASE={self.sql_database};"
            f"UID={self.sql_user};"
            f"PWD={self.sql_password};"
            "TrustServerCertificate=yes;"
            "Encrypt=no;"
        )


settings = Settings()
