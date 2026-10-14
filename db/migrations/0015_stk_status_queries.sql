BEGIN;

CREATE TABLE IF NOT EXISTS stk_push_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_request_id VARCHAR(100) NOT NULL,
    checkout_request_id VARCHAR(100) NOT NULL UNIQUE,
    request_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    last_query_response JSONB NULL,
    query_count INTEGER NOT NULL DEFAULT 0,
    last_queried_at TIMESTAMPTZ NULL,
    callback_received_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_stk_push_request_status CHECK (
        request_status IN ('PENDING', 'QUERY_ACCEPTED', 'SUCCEEDED', 'FAILED', 'CALLBACK_RECEIVED')
    )
);

CREATE INDEX IF NOT EXISTS idx_stk_push_requests_pending
    ON stk_push_requests (created_at)
    WHERE request_status IN ('PENDING', 'QUERY_ACCEPTED', 'SUCCEEDED');

REVOKE ALL ON stk_push_requests FROM PUBLIC, kodiflow_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON stk_push_requests TO kodiflow_system;

COMMIT;
