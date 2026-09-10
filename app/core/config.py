from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ============================================================
    # Application
    # ============================================================

    PROJECT_NAME: str = "KodiFlow Backend Engine"

    # ============================================================
    # PostgreSQL
    # ============================================================

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str = "127.0.0.1"
    POSTGRES_PORT: int = 5434

    DATABASE_URL: str

    # ============================================================
    # Redis
    # ============================================================

    REDIS_URL: str

    # ============================================================
    # M-Pesa Daraja
    # ============================================================

    MPESA_CONSUMER_KEY: str
    MPESA_CONSUMER_SECRET: str
    MPESA_PASSKEY: str
    MPESA_SHORTCODE: str

    MPESA_BASE_URL: str = "https://sandbox.safaricom.co.ke"

    MPESA_CALLBACK_URL: str

    # ============================================================
    # Environment configuration
    # ============================================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

