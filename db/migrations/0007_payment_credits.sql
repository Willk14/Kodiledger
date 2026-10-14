CREATE TABLE IF NOT EXISTS payment_credits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    payment_transaction_id UUID NOT NULL
        REFERENCES payment_transactions(id)
        ON DELETE RESTRICT,

    tenant_id UUID NOT NULL
        REFERENCES tenants(id)
        ON DELETE RESTRICT,

    amount NUMERIC(12,2) NOT NULL
        CHECK (amount > 0),

    status VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE'
        CHECK (status IN (
            'AVAILABLE',
            'APPLIED',
            'REFUNDED',
            'CANCELLED'
        )),

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    applied_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payment_credits_tenant
    ON payment_credits(tenant_id);

CREATE INDEX IF NOT EXISTS idx_payment_credits_payment_transaction
    ON payment_credits(payment_transaction_id);

CREATE INDEX IF NOT EXISTS idx_payment_credits_status
    ON payment_credits(status);
