BEGIN;

-- ============================================================
-- KodiLedger Migration 0011
-- RLS role hardening
-- ============================================================

-- ------------------------------------------------------------
-- 1. Trusted system database role
-- ------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'kodiflow_system'
    ) THEN
        CREATE ROLE kodiflow_system
        WITH LOGIN
        NOSUPERUSER
        NOCREATEDB
        NOCREATEROLE
        NOINHERIT
        BYPASSRLS;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE kodiflow_db TO kodiflow_system;
GRANT USAGE ON SCHEMA public TO kodiflow_system;
GRANT USAGE ON SCHEMA app TO kodiflow_system;

GRANT SELECT, INSERT, UPDATE, DELETE
ON ALL TABLES IN SCHEMA public
TO kodiflow_system;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLES
TO kodiflow_system;


-- ------------------------------------------------------------
-- 2. Remove all existing landlord-scoped policies that depend
--    on app.current_role()
-- ------------------------------------------------------------

DROP POLICY IF EXISTS landlords_scope_select ON landlords;
DROP POLICY IF EXISTS landlords_scope_insert ON landlords;
DROP POLICY IF EXISTS landlords_scope_update ON landlords;
DROP POLICY IF EXISTS landlords_scope_delete ON landlords;

DROP POLICY IF EXISTS properties_scope_select ON properties;
DROP POLICY IF EXISTS properties_scope_insert ON properties;
DROP POLICY IF EXISTS properties_scope_update ON properties;
DROP POLICY IF EXISTS properties_scope_delete ON properties;

DROP POLICY IF EXISTS units_scope_select ON units;
DROP POLICY IF EXISTS units_scope_insert ON units;
DROP POLICY IF EXISTS units_scope_update ON units;
DROP POLICY IF EXISTS units_scope_delete ON units;

DROP POLICY IF EXISTS tenants_scope_select ON tenants;
DROP POLICY IF EXISTS tenants_scope_insert ON tenants;
DROP POLICY IF EXISTS tenants_scope_update ON tenants;
DROP POLICY IF EXISTS tenants_scope_delete ON tenants;

DROP POLICY IF EXISTS invoices_scope_select ON invoices;
DROP POLICY IF EXISTS invoices_scope_insert ON invoices;
DROP POLICY IF EXISTS invoices_scope_update ON invoices;
DROP POLICY IF EXISTS invoices_scope_delete ON invoices;

DROP POLICY IF EXISTS ledger_entries_scope_select ON ledger_entries;
DROP POLICY IF EXISTS ledger_entries_scope_insert ON ledger_entries;
DROP POLICY IF EXISTS ledger_entries_scope_update ON ledger_entries;
DROP POLICY IF EXISTS ledger_entries_scope_delete ON ledger_entries;

DROP POLICY IF EXISTS payment_processing_scope_select ON payment_processing;
DROP POLICY IF EXISTS payment_processing_scope_insert ON payment_processing;
DROP POLICY IF EXISTS payment_processing_scope_update ON payment_processing;
DROP POLICY IF EXISTS payment_processing_scope_delete ON payment_processing;

DROP POLICY IF EXISTS payment_transactions_scope_select ON payment_transactions;
DROP POLICY IF EXISTS payment_transactions_scope_insert ON payment_transactions;
DROP POLICY IF EXISTS payment_transactions_scope_update ON payment_transactions;
DROP POLICY IF EXISTS payment_transactions_scope_delete ON payment_transactions;

DROP POLICY IF EXISTS payment_allocations_scope_select ON payment_allocations;
DROP POLICY IF EXISTS payment_allocations_scope_insert ON payment_allocations;
DROP POLICY IF EXISTS payment_allocations_scope_update ON payment_allocations;
DROP POLICY IF EXISTS payment_allocations_scope_delete ON payment_allocations;

DROP POLICY IF EXISTS payment_credits_scope_select ON payment_credits;
DROP POLICY IF EXISTS payment_credits_scope_insert ON payment_credits;
DROP POLICY IF EXISTS payment_credits_scope_update ON payment_credits;
DROP POLICY IF EXISTS payment_credits_scope_delete ON payment_credits;

DROP POLICY IF EXISTS unassigned_payments_scope_select ON unassigned_payments;
DROP POLICY IF EXISTS unassigned_payments_scope_insert ON unassigned_payments;
DROP POLICY IF EXISTS unassigned_payments_scope_update ON unassigned_payments;
DROP POLICY IF EXISTS unassigned_payments_scope_delete ON unassigned_payments;

DROP POLICY IF EXISTS utility_readings_scope_select ON utility_readings;
DROP POLICY IF EXISTS utility_readings_scope_insert ON utility_readings;
DROP POLICY IF EXISTS utility_readings_scope_update ON utility_readings;
DROP POLICY IF EXISTS utility_readings_scope_delete ON utility_readings;

DROP POLICY IF EXISTS user_device_tokens_scope_select ON user_device_tokens;
DROP POLICY IF EXISTS user_device_tokens_scope_insert ON user_device_tokens;
DROP POLICY IF EXISTS user_device_tokens_scope_update ON user_device_tokens;
DROP POLICY IF EXISTS user_device_tokens_scope_delete ON user_device_tokens;

-- Older redundant policies
DROP POLICY IF EXISTS landlord_properties_policy ON properties;
DROP POLICY IF EXISTS landlord_units_policy ON units;
DROP POLICY IF EXISTS landlord_ledger_policy ON ledger_entries;


-- ------------------------------------------------------------
-- 3. Remove current_role() only after its policy dependencies
--    have been removed
-- ------------------------------------------------------------

DROP FUNCTION IF EXISTS app.current_role();


-- ------------------------------------------------------------
-- 4. Landlords
-- ------------------------------------------------------------

CREATE POLICY landlords_scope_select
ON landlords
FOR SELECT
USING (
    id = app.current_landlord_id()
);

CREATE POLICY landlords_scope_insert
ON landlords
FOR INSERT
WITH CHECK (
    false
);

CREATE POLICY landlords_scope_update
ON landlords
FOR UPDATE
USING (
    id = app.current_landlord_id()
)
WITH CHECK (
    id = app.current_landlord_id()
);

CREATE POLICY landlords_scope_delete
ON landlords
FOR DELETE
USING (
    false
);


-- ------------------------------------------------------------
-- 5. Properties
-- ------------------------------------------------------------

CREATE POLICY properties_scope_select
ON properties
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY properties_scope_insert
ON properties
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY properties_scope_update
ON properties
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY properties_scope_delete
ON properties
FOR DELETE
USING (
    landlord_id = app.current_landlord_id()
);


-- ------------------------------------------------------------
-- 6. Units
-- ------------------------------------------------------------

CREATE POLICY units_scope_select
ON units
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY units_scope_insert
ON units
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY units_scope_update
ON units
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY units_scope_delete
ON units
FOR DELETE
USING (
    landlord_id = app.current_landlord_id()
);


-- ------------------------------------------------------------
-- 7. Tenants
-- ------------------------------------------------------------

CREATE POLICY tenants_scope_select
ON tenants
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY tenants_scope_insert
ON tenants
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY tenants_scope_update
ON tenants
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY tenants_scope_delete
ON tenants
FOR DELETE
USING (
    landlord_id = app.current_landlord_id()
);


-- ------------------------------------------------------------
-- 8. Invoices
-- ------------------------------------------------------------

CREATE POLICY invoices_scope_select
ON invoices
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY invoices_scope_insert
ON invoices
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY invoices_scope_update
ON invoices
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY invoices_scope_delete
ON invoices
FOR DELETE
USING (
    landlord_id = app.current_landlord_id()
);


-- ------------------------------------------------------------
-- 9. Ledger entries
-- ------------------------------------------------------------

CREATE POLICY ledger_entries_scope_select
ON ledger_entries
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY ledger_entries_scope_insert
ON ledger_entries
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY ledger_entries_scope_update
ON ledger_entries
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY ledger_entries_scope_delete
ON ledger_entries
FOR DELETE
USING (
    false
);


-- ------------------------------------------------------------
-- 10. Payment processing
-- ------------------------------------------------------------

CREATE POLICY payment_processing_scope_select
ON payment_processing
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY payment_processing_scope_insert
ON payment_processing
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY payment_processing_scope_update
ON payment_processing
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY payment_processing_scope_delete
ON payment_processing
FOR DELETE
USING (
    false
);


-- ------------------------------------------------------------
-- 11. Payment transactions
-- ------------------------------------------------------------

CREATE POLICY payment_transactions_scope_select
ON payment_transactions
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY payment_transactions_scope_insert
ON payment_transactions
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY payment_transactions_scope_update
ON payment_transactions
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY payment_transactions_scope_delete
ON payment_transactions
FOR DELETE
USING (
    false
);


-- ------------------------------------------------------------
-- 12. Payment allocations
-- ------------------------------------------------------------

CREATE POLICY payment_allocations_scope_select
ON payment_allocations
FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM payment_transactions pt
        WHERE pt.id = payment_allocations.payment_transaction_id
          AND pt.landlord_id = app.current_landlord_id()
    )
);

CREATE POLICY payment_allocations_scope_insert
ON payment_allocations
FOR INSERT
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM payment_transactions pt
        WHERE pt.id = payment_allocations.payment_transaction_id
          AND pt.landlord_id = app.current_landlord_id()
    )
);

CREATE POLICY payment_allocations_scope_update
ON payment_allocations
FOR UPDATE
USING (
    EXISTS (
        SELECT 1
        FROM payment_transactions pt
        WHERE pt.id = payment_allocations.payment_transaction_id
          AND pt.landlord_id = app.current_landlord_id()
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM payment_transactions pt
        WHERE pt.id = payment_allocations.payment_transaction_id
          AND pt.landlord_id = app.current_landlord_id()
    )
);

CREATE POLICY payment_allocations_scope_delete
ON payment_allocations
FOR DELETE
USING (
    false
);


-- ------------------------------------------------------------
-- 13. Payment credits
-- ------------------------------------------------------------

CREATE POLICY payment_credits_scope_select
ON payment_credits
FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM payment_transactions pt
        WHERE pt.id = payment_credits.payment_transaction_id
          AND pt.landlord_id = app.current_landlord_id()
    )
);

CREATE POLICY payment_credits_scope_insert
ON payment_credits
FOR INSERT
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM payment_transactions pt
        WHERE pt.id = payment_credits.payment_transaction_id
          AND pt.landlord_id = app.current_landlord_id()
    )
);

CREATE POLICY payment_credits_scope_update
ON payment_credits
FOR UPDATE
USING (
    EXISTS (
        SELECT 1
        FROM payment_transactions pt
        WHERE pt.id = payment_credits.payment_transaction_id
          AND pt.landlord_id = app.current_landlord_id()
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM payment_transactions pt
        WHERE pt.id = payment_credits.payment_transaction_id
          AND pt.landlord_id = app.current_landlord_id()
    )
);

CREATE POLICY payment_credits_scope_delete
ON payment_credits
FOR DELETE
USING (
    false
);


-- ------------------------------------------------------------
-- 14. Unassigned payments
-- ------------------------------------------------------------

CREATE POLICY unassigned_payments_scope_select
ON unassigned_payments
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY unassigned_payments_scope_insert
ON unassigned_payments
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY unassigned_payments_scope_update
ON unassigned_payments
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY unassigned_payments_scope_delete
ON unassigned_payments
FOR DELETE
USING (
    false
);


-- ------------------------------------------------------------
-- 15. Utility readings
-- ------------------------------------------------------------

CREATE POLICY utility_readings_scope_select
ON utility_readings
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY utility_readings_scope_insert
ON utility_readings
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY utility_readings_scope_update
ON utility_readings
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY utility_readings_scope_delete
ON utility_readings
FOR DELETE
USING (
    false
);


-- ------------------------------------------------------------
-- 16. Device tokens
-- ------------------------------------------------------------

CREATE POLICY user_device_tokens_scope_select
ON user_device_tokens
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY user_device_tokens_scope_insert
ON user_device_tokens
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY user_device_tokens_scope_update
ON user_device_tokens
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
);

CREATE POLICY user_device_tokens_scope_delete
ON user_device_tokens
FOR DELETE
USING (
    false
);


-- ------------------------------------------------------------
-- 17. Remove normal application access to internal integration
--     infrastructure.
-- ------------------------------------------------------------

REVOKE ALL
ON TABLE raw_payment_webhooks
FROM kodiflow_app;

REVOKE ALL
ON TABLE outbox_events
FROM kodiflow_app;

GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLE raw_payment_webhooks
TO kodiflow_system;

GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLE outbox_events
TO kodiflow_system;


COMMIT;
