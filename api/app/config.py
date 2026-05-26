"""Application settings loaded from environment / .env via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Anthropic ----
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # ---- SQL Server ----
    sql_server: str = "localhost"
    sql_database: str = "pymeconta_local"
    sql_user: str = "sa"
    sql_password: str = ""
    sql_driver: str = "{ODBC Driver 17 for SQL Server}"
    sql_pool_size: int = 10

    # ---- JWT ----
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # ---- Logging ----
    log_level: str = "INFO"
    log_json: bool = False

    # ---- Rate limits ----
    rate_limit_tenant_hour: int = 100
    rate_limit_user_hour: int = 30
    rate_limit_tokens_day: int = 1_000_000

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
