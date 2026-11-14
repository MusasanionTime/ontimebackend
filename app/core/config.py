from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ONTIME SUBDATA LTD"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    DATABASE_URL: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/ontime_subdata"
    )

    REDIS_URL: str = "redis://localhost:6379/0"

    SECRET_KEY: str = "CHANGE_THIS_IN_PRODUCTION"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Monnify
    MONNIFY_BASE_URL: str = ""
    MONNIFY_API_KEY: str = ""
    MONNIFY_SECRET_KEY: str = ""
    MONNIFY_CONTRACT_CODE: str = ""

    # Topify Dedicated Virtual Accounts. Keep disabled until an approved
    # businessId and the appropriate test/live credentials are configured.
    TOPIFY_ENABLED: bool = False
    TOPIFY_BASE_URL: str = "https://apipay.topify.ng"
    TOPIFY_API_KEY: str = ""
    TOPIFY_WEBHOOK_SECRET: str = ""
    TOPIFY_BUSINESS_ID: str = ""

    # BTPass
    BTPASS_BASE_URL: str = ""
    BTPASS_API_KEY: str = ""

    # ChangeNOW
    CHANGENOW_BASE_URL: str = ""
    CHANGENOW_API_KEY: str = ""
    CHANGENOW_WEBHOOK_SECRET: str = ""

    # Bigisub
    BIGISUB_BASE_URL: str = ""
    BIGISUB_API_KEY: str = ""
    # Configure from BigiSub Settings > API Doc. Never use the customer PIN here.
    BIGISUB_PROVIDER_PIN: str = ""
    # Legacy VTU purchase path; override if BigiSub documents a different path.
    BIGISUB_DATA_PURCHASE_PATH: str = ""

    # Other crypto provider
    CRYPTO_API_BASE_URL: str = ""
    CRYPTO_API_KEY: str = ""

    # SMTP / Email
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "ONTIME SUBDATA LTD"

    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
