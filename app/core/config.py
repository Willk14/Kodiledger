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

    RATE_LIMIT_STK_PUSH_REQUESTS: int = 5
    RATE_LIMIT_STK_PUSH_WINDOW_SECONDS: int = 60

    # ============================================================
    # M-Pesa Daraja
    # ============================================================

    MPESA_CONSUMER_KEY: str
    MPESA_CONSUMER_SECRET: str
    MPESA_PASSKEY: str
    MPESA_SHORTCODE: str

    MPESA_BASE_URL: str = "https://sandbox.safaricom.co.ke"
    MPESA_CALLBACK_URL: str
    MPESA_CALLBACK_ALLOWED_IPS: str = (
        "196.201.214.200,196.201.214.206,196.201.213.114,196.201.214.207,"
        "196.201.214.208,196.201.213.44,196.201.212.127,196.201.212.138,"
        "196.201.212.129,196.201.212.136,196.201.212.74,196.201.212.69"
    )
    MPESA_CALLBACK_TOKEN: str = ""

    # ============================================================
    # CORS
    # ============================================================

    CORS_ALLOWED_ORIGINS: str = ""

    # ============================================================
    # Authentication / Security
    # ============================================================

    OIDC_ISSUER_URL: str = ""
    OIDC_AUDIENCE: str = ""
    OIDC_JWKS_URL: str = ""
    OIDC_SIGNING_ALGORITHMS: str = "RS256"
    OIDC_JWKS_TIMEOUT_SECONDS: int = Field(default=5, ge=1, le=30)

    # ============================================================
    # Environment configuration
    # ============================================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    KAFKA_BOOTSTRAP_SERVERS: str = "127.0.0.1:9092"
    KAFKA_PAYMENT_TOPIC: str = "payment.processed"

    # ============================================================
    # Transactional outbox delivery
    # ============================================================

    OUTBOX_BATCH_SIZE: int = Field(default=100, ge=1, le=1000)
    OUTBOX_MAX_BATCH_WAIT_MS: int = Field(default=1000, ge=0, le=60_000)
    OUTBOX_POLL_INTERVAL_MS: int = Field(default=500, ge=1, le=60_000)
    OUTBOX_LOCK_TIMEOUT_SECONDS: int = Field(default=300, ge=1, le=86_400)


settings = Settings()

