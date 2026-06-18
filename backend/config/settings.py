"""
Application settings for MGNREGA Verification & Fraud Intelligence System.

Uses pydantic-settings to load configuration from environment variables
and .env files with validation and type coercion.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Resolve project root (parent of the `config/` package)
# ---------------------------------------------------------------------------
_BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Central configuration loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=str(_BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- Database (PostGIS) ------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg2://mgnrega_user:password@localhost:5432/mgnrega_verification",
        description="SQLAlchemy connection string for PostGIS database",
    )
    database_pool_size: int = Field(default=10, ge=1, le=50)
    database_max_overflow: int = Field(default=20, ge=0, le=100)
    database_echo: bool = Field(default=False)

    # ----- Redis -------------------------------------------------------------
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_cache_ttl: int = Field(default=3600, ge=60, description="Cache TTL in seconds")

    # ----- Copernicus / Sentinel-2 -------------------------------------------
    copernicus_client_id: str = Field(default="")
    copernicus_client_secret: str = Field(default="")
    copernicus_token_url: str = Field(
        default="https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
    )

    # ----- Sentinel Hub ------------------------------------------------------
    sentinelhub_client_id: str = Field(default="")
    sentinelhub_client_secret: str = Field(default="")
    sentinelhub_base_url: str = Field(default="https://services.sentinel-hub.com")

    # ----- Groq LLM ----------------------------------------------------------
    groq_api_key: str = Field(default="")
    groq_model: str = Field(default="openai/gpt-oss-120b")
    groq_base_url: str = Field(default="https://api.groq.com/openai/v1")

    # ----- data.gov.in (real MGNREGA figures) --------------------------------
    datagovin_api_key: str = Field(default="")
    datagovin_resource_id: str = Field(default="")

    # ----- NREGA Public Portal -----------------------------------------------
    nrega_base_url: str = Field(default="https://nrega.nic.in")
    nrega_api_timeout: int = Field(default=30, ge=5, le=120)
    nrega_max_retries: int = Field(default=3, ge=1, le=10)

    # ----- ISRO Bhuvan -------------------------------------------------------
    bhuvan_api_key: str = Field(default="")
    bhuvan_base_url: str = Field(default="https://bhuvan-vec2.nrsc.gov.in")

    # ----- Ollama (Local LLM) ------------------------------------------------
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="llama3")
    ollama_timeout: int = Field(default=120, ge=10, le=600)

    # ----- Bhashini NLP / Translation ----------------------------------------
    bhashini_api_key: str = Field(default="")
    bhashini_base_url: str = Field(default="https://dhruva-api.bhashini.gov.in")

    # ----- Security ----------------------------------------------------------
    secret_key: str = Field(
        default="CHANGE-ME-IN-PRODUCTION",
        min_length=16,
        description="JWT signing key",
    )
    access_token_expire_minutes: int = Field(default=60, ge=5, le=1440)
    algorithm: str = Field(default="HS256")

    # ----- Celery ------------------------------------------------------------
    celery_broker_url: str = Field(default="redis://localhost:6379/1")
    celery_result_backend: str = Field(default="redis://localhost:6379/2")
    celery_task_serializer: str = Field(default="json")
    celery_result_serializer: str = Field(default="json")

    # ----- Feature Toggles ---------------------------------------------------
    enable_satellite_verification: bool = Field(default=True)
    enable_payment_anomaly_detection: bool = Field(default=True)
    enable_muster_roll_analysis: bool = Field(default=True)
    enable_photo_verification: bool = Field(default=True)
    enable_auto_investigation: bool = Field(default=False)
    enable_bhashini_translation: bool = Field(default=False)
    enable_ollama_reports: bool = Field(default=True)

    # ----- Verification Thresholds -------------------------------------------
    area_mismatch_threshold_percent: float = Field(
        default=20.0,
        ge=1.0,
        le=100.0,
        description="Percentage deviation between reported and satellite-measured area to flag",
    )
    ndvi_change_threshold: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Minimum NDVI change to consider vegetation impact significant",
    )
    payment_anomaly_zscore_threshold: float = Field(
        default=2.5,
        ge=1.0,
        le=5.0,
        description="Z-score threshold for flagging payment outliers",
    )
    attendance_anomaly_threshold_days: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Consecutive suspicious attendance days to trigger anomaly",
    )
    gps_distance_tolerance_meters: float = Field(
        default=500.0,
        ge=10.0,
        le=5000.0,
        description="Max acceptable distance between reported and actual GPS coordinates",
    )

    # ----- Logging -----------------------------------------------------------
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/mgnrega_verification.log")
    log_rotation: str = Field(default="10 MB")
    log_retention: str = Field(default="30 days")

    # ----- Validators --------------------------------------------------------
    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got '{v}'")
        return upper

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        if not v.startswith(("postgresql", "sqlite")):
            raise ValueError(
                "database_url must start with 'postgresql' (or 'sqlite' for testing)"
            )
        return v

    @field_validator("algorithm")
    @classmethod
    def _validate_algorithm(cls, v: str) -> str:
        allowed = {"HS256", "HS384", "HS512"}
        if v not in allowed:
            raise ValueError(f"algorithm must be one of {allowed}")
        return v

    # ----- Computed Properties -----------------------------------------------
    @computed_field  # type: ignore[misc]
    @property
    def async_database_url(self) -> str:
        """Return an asyncpg-compatible URL derived from the sync one."""
        return self.database_url.replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        ).replace("postgresql://", "postgresql+asyncpg://")

    @computed_field  # type: ignore[misc]
    @property
    def base_dir(self) -> str:
        """Absolute path to the backend root directory."""
        return str(_BASE_DIR)

    @computed_field  # type: ignore[misc]
    @property
    def log_file_path(self) -> str:
        """Fully resolved log file path."""
        log_path = Path(self.log_file)
        if not log_path.is_absolute():
            log_path = _BASE_DIR / log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        return str(log_path)

    @computed_field  # type: ignore[misc]
    @property
    def satellite_apis_configured(self) -> bool:
        """True when at least one satellite data source has credentials."""
        return bool(self.copernicus_client_id and self.copernicus_client_secret) or bool(
            self.sentinelhub_client_id and self.sentinelhub_client_secret
        )

    @computed_field  # type: ignore[misc]
    @property
    def nrega_muster_roll_url(self) -> str:
        """Full URL for the NREGA muster roll search endpoint."""
        return f"{self.nrega_base_url}/netnrega/stms_actionmusterrolls.aspx"

    @computed_field  # type: ignore[misc]
    @property
    def nrega_job_card_url(self) -> str:
        """Full URL for the NREGA job card search endpoint."""
        return f"{self.nrega_base_url}/netnrega/IndexFrame.aspx"

    @computed_field  # type: ignore[misc]
    @property
    def nrega_fto_url(self) -> str:
        """Full URL for the NREGA Fund Transfer Order search."""
        return f"{self.nrega_base_url}/Aborneregp/FTO/FTOReport.aspx"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton of the application settings.

    Call ``get_settings.cache_clear()`` in tests to reload.
    """
    return Settings()
