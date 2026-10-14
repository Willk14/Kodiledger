BEGIN;

ALTER TABLE outbox_events
ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_outbox_events_claimable
    ON outbox_events (status, available_at, created_at)
    WHERE status = 'PENDING';

COMMIT;
