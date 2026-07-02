"""Application settings loaded from environment variables (via .env file).

All variables map 1:1 with backend/.env.example.
No variable is added or removed outside the documented .env.example.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Pydantic Settings — reads from .env, validates types automatically."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- App ----------
    app_env: str = "development"
    app_debug: bool = True
    api_v1_prefix: str = "/api/v1"
    api_key: str = "change-me-to-a-random-secret"

    # ---------- Database (PostgreSQL) ----------
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/marketing_analytics"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ---------- Redis (Celery broker + cache layer) ----------
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ---------- Cache TTL (seconds) ----------
    cache_ttl_recent: int = 300
    cache_ttl_historical: int = 3600

    # ---------- Facebook Marketing API ----------
    facebook_app_id: str = ""
    facebook_app_secret: str = ""
    facebook_access_token: str = ""
    facebook_api_version: str = "v19.0"

    # ---------- TikTok Ads API (để trống — dùng ở đợt 2) ----------
    tiktok_app_id: str = ""
    tiktok_app_secret: str = ""
    tiktok_access_token: str = ""

    # ---------- Google Ads API (để trống — dùng ở đợt 2) ----------
    google_ads_developer_token: str = ""
    google_ads_client_id: str = ""
    google_ads_client_secret: str = ""
    google_ads_refresh_token: str = ""
    google_ads_login_customer_id: str = ""

    # ---------- Rate limit (mặc định, có thể override theo platform) ----------
    rate_limit_facebook_per_min: int = 200
    rate_limit_tiktok_per_min: int = 100
    rate_limit_google_per_min: int = 150


settings = Settings()