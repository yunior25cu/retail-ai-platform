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
    # Azure SQL exige conexion cifrada: SQL_ENCRYPT=yes y SQL_TRUST_SERVER_CERTIFICATE=no.
    # Los defaults mantienen el comportamiento local de siempre (SQL Server Express).
    sql_encrypt: str = "no"
    sql_trust_server_certificate: str = "yes"
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

    # ── Balaxys ERP via MCP (chat interno como cliente MCP) ──────────────────
    # El ERP manda un token de vida corta en X-Balaxys-Mcp-Token por mensaje; con
    # el, el orquestador usa las tools ERP de {balaxys_mcp_url}. URL vacia o
    # enabled=False -> solo flujo retail (comportamiento previo).
    balaxys_mcp_enabled: bool = True
    balaxys_mcp_url: str = ""              # p.ej. https://<api-balaxys>/mcp
    balaxys_mcp_timeout_seconds: float = 30.0
    balaxys_mcp_max_tool_calls: int = 8    # tope de llamadas ERP por mensaje
    balaxys_mcp_verify_tls: bool = True    # False solo para un cert de desarrollo local
    balaxys_mcp_role_subset: bool = True   # menos tools (y tokens) para roles no-direccion

    # ── Tools retail (almacen gold) ───────────────────────────────────────────
    # False = modo "solo ERP": el chat no ofrece las tools retail (que leen el
    # almacen gold.*) y usa un system prompt neutro. Para ambientes donde gold
    # no existe (p.ej. Balaxys dev en Azure): ahi el chat trabaja solo con las
    # tools ERP via MCP. docs/deploy-azure-dev.md
    retail_tools_enabled: bool = True

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Comma-separated origins. In dev: http://localhost:5173,http://localhost:5174
    cors_origins: str = "http://localhost:5173,http://localhost:5174"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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
            f"TrustServerCertificate={self.sql_trust_server_certificate};"
            f"Encrypt={self.sql_encrypt};"
        )


settings = Settings()
