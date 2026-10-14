-- ============================================================
-- KodiLedger Migration 0005
-- Payment allocation layer
-- ============================================================

CREATE TYPE payment_allocation_status_enum AS ENUM (
    'ALLOCATED',
    'REVERSED'
);

CREATE TABLE IF NOT EXISTS payment_allocations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    payment_transaction_id UUID NOT NULL
        REFERENCES payment_transactions(id) ON DELETE RESTRICT,

    invoice_id UUID NOT NULL
        REFERENCES invoices(id) ON DELETE RESTRICT,

    amount NUMERIC(12, 2) NOT NULL,

    status payment_allocation_status_enum NOT NULL
        DEFAULT 'ALLOCATED',

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    reversed_at TIMESTAMPTZ NULL,

    CONSTRAINT chk_payment_allocations_amount
        CHECK (amount > 0),

    CONSTRAINT uq_payment_allocation_payment_invoice
        UNIQUE (payment_transaction_id, invoice_id)
);

CREATE INDEX IF NOT EXISTS idx_payment_allocations_payment
    ON payment_allocations(payment_transaction_id);

CREATE INDEX IF NOT EXISTS idx_payment_allocations_invoice
    ON payment_allocations(invoice_id);

CREATE INDEX IF NOT EXISTS idx_payment_allocations_status
    ON payment_allocations(status);
