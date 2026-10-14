BEGIN;

ALTER TABLE raw_payment_webhooks
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS retry_exhausted_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_raw_webhooks_retry
    ON raw_payment_webhooks (next_attempt_at, created_at)
    WHERE processed = FALSE;

COMMIT;
