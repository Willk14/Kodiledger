BEGIN;

ALTER TABLE stk_push_requests
    ADD COLUMN invoice_id UUID NULL
    REFERENCES invoices(id) ON DELETE SET NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON stk_push_requests TO kodiflow_system;

CREATE INDEX idx_stk_push_requests_invoice
    ON stk_push_requests (invoice_id)
    WHERE invoice_id IS NOT NULL;

COMMIT;
