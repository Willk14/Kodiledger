BEGIN;

-- Landlord-facing payment resolution records a payment event in the outbox.
-- Keep the application role limited to payment-transaction events that
-- belong to its transaction-local landlord RLS context.
ALTER TABLE outbox_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS outbox_payment_scope_select ON outbox_events;
DROP POLICY IF EXISTS outbox_payment_scope_insert ON outbox_events;

GRANT SELECT, INSERT ON TABLE outbox_events TO kodiflow_app;

CREATE POLICY outbox_payment_scope_select
ON outbox_events
FOR SELECT
TO kodiflow_app
USING (
    aggregate_type = 'PAYMENT_TRANSACTION'
    AND EXISTS (
        SELECT 1
        FROM payment_transactions AS payment
        WHERE payment.id = outbox_events.aggregate_id
          AND payment.landlord_id = app.current_landlord_id()
    )
);

CREATE POLICY outbox_payment_scope_insert
ON outbox_events
FOR INSERT
TO kodiflow_app
WITH CHECK (
    aggregate_type = 'PAYMENT_TRANSACTION'
    AND EXISTS (
        SELECT 1
        FROM payment_transactions AS payment
        WHERE payment.id = outbox_events.aggregate_id
          AND payment.landlord_id = app.current_landlord_id()
    )
);

COMMIT;
