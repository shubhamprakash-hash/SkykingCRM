import secrets, logging
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("skyking")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"            # development | production
    DATABASE_URL: str = "sqlite:///./skyking.db"
    SECRET_KEY: str = ""                    # REQUIRED in production
    ACCESS_TOKEN_MINUTES: int = 30
    REFRESH_TOKEN_DAYS: int = 7
    MAX_FAILED_LOGINS: int = 5
    LOCKOUT_MINUTES: int = 15
    CORS_ORIGINS: str = "http://localhost:5173"

    # first super-admin (created by `python -m app.seed`); no default password exists
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""

    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_MB: int = 10

    # intake
    WEBHOOK_SECRET: str = ""                # shared secret for /intake webhooks
    USE_MOCK_MSG91: bool = True
    MSG91_AUTHKEY: str = ""
    MSG91_BASE_URL: str = "https://control.msg91.com/api/v5/hello"
    MOCK_MSG91_FILE: str = "app/mock_data/msg91_tickets_sample.json"
    MSG91_SEND_URL: str = ""                # outbound WhatsApp/SMS template endpoint (confirm with MSG91)
    IMAP_HOST: str = ""
    IMAP_USER: str = ""
    IMAP_PASSWORD: str = ""
    IMAP_FOLDER: str = "INBOX"

    WORKER_INTERVAL_SECONDS: int = 60


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.SECRET_KEY:
        if s.APP_ENV == "production":
            raise RuntimeError("SECRET_KEY must be set in production")
        s.SECRET_KEY = secrets.token_urlsafe(48)     # ephemeral dev key
        log.warning("SECRET_KEY not set: using an ephemeral development key")
    return s
