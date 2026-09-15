from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ============================================================
    # Application
    # ============================================================

    PROJECT_NAME: str = "KodiFlow Backend Engine"

    ENVIRONMENT: str = Field(
        default="development",
        validation_alias="ENVIRONMENT",
    )

    DEBUG: bool = Field(
        default=False,
        validation_alias="DEBUG",
    )

    # ============================================================
    # PostgreSQL
    # ============================================================

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str = "127.0.0.1"
    POSTGRES_PORT: int = 5434

    DATABASE_URL: str
    SYSTEM_DATABASE_URL: str

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
    # CORS
    # ============================================================

    CORS_ALLOWED_ORIGINS: str = ""

    # ============================================================
    # Authentication / Security
    # ============================================================

    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ============================================================
    # Environment configuration
    # ============================================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


settings = Settings()

