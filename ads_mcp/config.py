"""Settings loaded from environment variables (or a .env file)."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Project-root .env, so it is found no matter which directory the client launches us from.
load_dotenv(os.getenv("ADS_MCP_ENV_FILE", Path(__file__).resolve().parent.parent / ".env"))


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, "").split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    # Google (one OAuth client + refresh token covers Google Ads and GA4)
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_refresh_token: str = os.getenv("GOOGLE_REFRESH_TOKEN", "")
    google_ads_developer_token: str = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
    google_ads_login_customer_id: str = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").replace("-", "")

    # Meta
    meta_access_token: str = os.getenv("META_ACCESS_TOKEN", "")
    meta_api_version: str = os.getenv("META_API_VERSION", "v24.0")

    # Safety
    allow_writes: bool = _bool("ALLOW_WRITES", False)
    max_daily_budget: float = float(os.getenv("MAX_DAILY_BUDGET", "500"))
    allowed_google_ads_customers: list[str] = field(
        default_factory=lambda: [c.replace("-", "") for c in _list("ALLOWED_GOOGLE_ADS_CUSTOMERS")]
    )
    allowed_meta_ad_accounts: list[str] = field(default_factory=lambda: _list("ALLOWED_META_AD_ACCOUNTS"))
    audit_log_path: str = os.getenv("AUDIT_LOG_PATH", "audit_log.jsonl")

    # HTTP server
    mcp_api_key: str = os.getenv("MCP_API_KEY", "")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))


settings = Settings()
