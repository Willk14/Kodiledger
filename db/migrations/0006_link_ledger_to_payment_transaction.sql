-- ============================================================
-- KodiLedger Migration 0006
-- Link accounting ledger entries to payment transactions
-- ============================================================

ALTER TABLE ledger_entries
ADD COLUMN IF NOT EXISTS payment_transaction_id UUID NULL
    REFERENCES payment_transactions(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_ledger_payment_transaction
    ON ledger_entries(payment_transaction_id);
