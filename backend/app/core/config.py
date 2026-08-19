"""
Central configuration. All MSG91-specific business rules (inbox id, team id,
etc.) are loaded from env vars / DB config table -- NEVER hardcoded in logic,
per the requirement that Support Team ID / Inbox ID may change over time.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # --- App ---
    APP_NAME: str = "SkyKing CRM"
    ENV: str = "development"
    SECRET_KEY: str = "change-me-in-prod"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12

    # --- Database ---
    DATABASE_URL: str = "postgresql+psycopg2://skyking:skyking@localhost:5432/skyking_crm"

    # --- MSG91 Hello API ---
    MSG91_BASE_URL: str = "https://api.msg91.com/api/v5/hello"
    MSG91_AUTHKEY: str = ""  # NEVER exposed to frontend, backend-only
    MSG91_COMPANY_ID: int = 109474

    # When true, the sync service reads from app/mock_data/*.json instead of
    # calling the live MSG91 API. Flip to False (or unset) once real MSG91
    # credentials/API access are ready -- no other code needs to change,
    # since sync_service.py always goes through Msg91Client.get_tickets().
    USE_MOCK_MSG91: bool = True
    MOCK_MSG91_FILE: str = "app/mock_data/msg91_tickets_sample.json"

    # Default business-rule values. These are *seed* defaults only -- the
    # authoritative values live in the `system_config` DB table and are
    # editable by Admins at runtime (see services/config_service.py).
    DEFAULT_WHATSAPP_INBOX_ID: int = 2271
    DEFAULT_SUPPORT_TEAM_ID: int = 2253
    DEFAULT_ORIGIN: str = "whatsapp"
    DEFAULT_ASSIGNEE_TYPE: str = "team"

    # --- Sync ---
    MSG91_SYNC_INTERVAL_SECONDS: int = 60

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
