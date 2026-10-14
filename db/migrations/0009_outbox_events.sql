CREATE TABLE IF NOT EXISTS outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    event_type VARCHAR(100) NOT NULL,

    aggregate_type VARCHAR(100) NOT NULL,

    aggregate_id UUID NOT NULL,

    idempotency_key VARCHAR(255) NOT NULL UNIQUE,

    payload JSONB NOT NULL,

    status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'PUBLISHED', 'FAILED')),

    attempts INTEGER NOT NULL DEFAULT 0
        CHECK (attempts >= 0),

    available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    published_at TIMESTAMPTZ NULL,

    last_error TEXT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_outbox_events_pending
    ON outbox_events (status, available_at, created_at);

CREATE INDEX IF NOT EXISTS idx_outbox_events_aggregate
    ON outbox_events (aggregate_type, aggregate_id);

CREATE INDEX IF NOT EXISTS idx_outbox_events_created_at
    ON outbox_events (created_at);

