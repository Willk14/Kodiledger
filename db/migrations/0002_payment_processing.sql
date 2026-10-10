-- Payment processing/idempotency state for M-Pesa webhook handling.

CREATE TABLE IF NOT EXISTS payment_processing (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mpesa_receipt_number VARCHAR(100) NOT NULL UNIQUE,
    raw_webhook_id UUID NOT NULL
        REFERENCES raw_payment_webhooks(id) ON DELETE RESTRICT,
    landlord_id UUID NOT NULL
        REFERENCES landlords(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_payment_processing_landlord
    ON payment_processing(landlord_id);

CREATE INDEX IF NOT EXISTS idx_payment_processing_webhook
    ON payment_processing(raw_webhook_id);

CREATE INDEX IF NOT EXISTS idx_payment_processing_receipt
    ON payment_processing(mpesa_receipt_number);

ALTER TABLE payment_processing
    ADD CONSTRAINT chk_payment_processing_status
    CHECK (status IN ('PROCESSING', 'COMPLETED', 'FAILED', 'UNASSIGNED'));
