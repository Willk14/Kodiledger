-- Immutable applications of tenant payment credits to invoices.
CREATE TABLE IF NOT EXISTS payment_credit_applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_credit_id UUID NOT NULL
        REFERENCES payment_credits(id) ON DELETE RESTRICT,
    invoice_id UUID NOT NULL
        REFERENCES invoices(id) ON DELETE RESTRICT,
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    application_key VARCHAR(160) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_payment_credit_application_credit_invoice
        UNIQUE (payment_credit_id, invoice_id)
);

CREATE INDEX IF NOT EXISTS idx_payment_credit_applications_invoice
    ON payment_credit_applications(invoice_id);
CREATE INDEX IF NOT EXISTS idx_payment_credit_applications_credit
    ON payment_credit_applications(payment_credit_id);

ALTER TABLE payment_credit_applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_credit_applications FORCE ROW LEVEL SECURITY;

CREATE POLICY payment_credit_applications_scope_select
ON payment_credit_applications FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM payment_credits pc
        JOIN payment_transactions pt ON pt.id = pc.payment_transaction_id
        JOIN invoices i ON i.id = payment_credit_applications.invoice_id
        WHERE pc.id = payment_credit_applications.payment_credit_id
          AND pc.tenant_id = i.tenant_id
          AND pt.landlord_id = app.current_landlord_id()
          AND i.landlord_id = app.current_landlord_id()
    )
);

CREATE POLICY payment_credit_applications_scope_insert
ON payment_credit_applications FOR INSERT
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM payment_credits pc
        JOIN payment_transactions pt ON pt.id = pc.payment_transaction_id
        JOIN invoices i ON i.id = payment_credit_applications.invoice_id
        WHERE pc.id = payment_credit_applications.payment_credit_id
          AND pc.tenant_id = i.tenant_id
          AND pt.landlord_id = app.current_landlord_id()
          AND i.landlord_id = app.current_landlord_id()
    )
);

CREATE POLICY payment_credit_applications_scope_update
ON payment_credit_applications FOR UPDATE USING (false) WITH CHECK (false);
CREATE POLICY payment_credit_applications_scope_delete
ON payment_credit_applications FOR DELETE USING (false);

GRANT SELECT, INSERT ON payment_credit_applications TO kodiflow_app;
REVOKE UPDATE, DELETE, TRUNCATE ON payment_credit_applications FROM kodiflow_app;

