-- ============================================================
-- KodiLedger Migration 0004
-- Normalized payment transaction layer
-- ============================================================

CREATE TYPE payment_transaction_status_enum AS ENUM (
    'PENDING',
    'COMPLETED',
    'FAILED',
    'CANCELLED',
    'REVERSED'
);

CREATE TABLE IF NOT EXISTS payment_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    landlord_id UUID NOT NULL
        REFERENCES landlords(id) ON DELETE RESTRICT,

    tenant_id UUID NULL
        REFERENCES tenants(id) ON DELETE SET NULL,

    raw_webhook_id UUID NULL
        REFERENCES raw_payment_webhooks(id) ON DELETE SET NULL,

    merchant_request_id VARCHAR(100) NULL,
    checkout_request_id VARCHAR(100) NULL,

    mpesa_receipt_number VARCHAR(100) NOT NULL UNIQUE,

    payer_phone VARCHAR(15) NULL,
    payer_name VARCHAR(255) NULL,

    amount NUMERIC(12, 2) NOT NULL,

    payment_method payment_method_enum NOT NULL,

    status payment_transaction_status_enum NOT NULL
        DEFAULT 'PENDING',

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    completed_at TIMESTAMPTZ NULL,

    CONSTRAINT chk_payment_transactions_amount
        CHECK (amount > 0)
);

CREATE INDEX IF NOT EXISTS idx_payment_transactions_landlord
    ON payment_transactions(landlord_id);

CREATE INDEX IF NOT EXISTS idx_payment_transactions_tenant
    ON payment_transactions(tenant_id);

CREATE INDEX IF NOT EXISTS idx_payment_transactions_receipt
    ON payment_transactions(mpesa_receipt_number);

CREATE INDEX IF NOT EXISTS idx_payment_transactions_raw_webhook
    ON payment_transactions(raw_webhook_id);

CREATE INDEX IF NOT EXISTS idx_payment_transactions_merchant_request
    ON payment_transactions(merchant_request_id);

CREATE INDEX IF NOT EXISTS idx_payment_transactions_checkout_request
    ON payment_transactions(checkout_request_id);
