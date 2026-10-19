"""Application settings, loaded from environment variables / the project .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATABASE_DIR = PROJECT_ROOT / "database"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"

    # --- MySQL server -------------------------------------------------------
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_name: str = "oems_db"
    lab_db_name: str = "oems_lab"
    # host part of the MySQL accounts created by init_db.py ('localhost' or '%')
    db_account_host: str = "localhost"

    # administrator: used ONLY by scripts/init_db.py and the test suite, never by the API
    mysql_admin_user: str = "root"
    mysql_admin_password: SecretStr = SecretStr("")

    # least-privilege accounts used by the API
    db_app_user: str = "oems_app"
    db_app_password: SecretStr = SecretStr("change_me_app_1")
    db_readonly_user: str = "oems_reader"
    db_readonly_password: SecretStr = SecretStr("change_me_reader_1")
    db_lab_user: str = "oems_lab"
    db_lab_password: SecretStr = SecretStr("change_me_lab_1")
    db_dcl_user: str = "oems_lab_dcl"
    db_dcl_password: SecretStr = SecretStr("change_me_dcl_1")

    # --- auth ---------------------------------------------------------------
    jwt_secret: SecretStr = SecretStr("dev-only-secret-change-me-please-32chars")
    jwt_expire_minutes: int = 240

    # --- HTTP ---------------------------------------------------------------
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    max_request_bytes: int = 256 * 1024

    # --- DBMS lab -----------------------------------------------------------
    sql_freeform_enabled: bool = False
    sql_max_rows: int = 500
    sql_timeout_seconds: int = 10
    sql_rate_limit_per_minute: int = 30
    login_rate_limit_per_minute: int = 10

    # --- data / monitoring ----------------------------------------------------
    bulk_students: int = 3000
    lab_bulk_students: int = 1500
    slow_query_ms: float = 200.0

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("db_name", "lab_db_name")
    @classmethod
    def _safe_db_name(cls, value: str) -> str:
        # database names are interpolated into DDL by init_db.py, so restrict them
        if not value.replace("_", "").isalnum():
            raise ValueError("database names may contain only letters, digits and underscores")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
