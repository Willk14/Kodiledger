BEGIN;

-- ============================================================
-- KodiFlow RLS foundation
-- Migration: 0010_row_level_security.sql
-- ============================================================

-- ------------------------------------------------------------
-- Security context helpers
-- ------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS app;

CREATE OR REPLACE FUNCTION app.current_landlord_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(
        current_setting('app.current_landlord_id', true),
        ''
    )::uuid;
$$;

CREATE OR REPLACE FUNCTION app.current_user_id()
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(
        current_setting('app.current_user_id', true),
        ''
    );
$$;

CREATE OR REPLACE FUNCTION app.current_role()
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(
        current_setting('app.current_role', true),
        ''
    );
$$;


-- ============================================================
-- Enable RLS
-- ============================================================

ALTER TABLE landlords ENABLE ROW LEVEL SECURITY;
ALTER TABLE properties ENABLE ROW LEVEL SECURITY;
ALTER TABLE units ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledger_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_processing ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_allocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_credits ENABLE ROW LEVEL SECURITY;
ALTER TABLE unassigned_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE utility_readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_device_tokens ENABLE ROW LEVEL SECURITY;


-- ============================================================
-- LANDLORDS
-- ============================================================

DROP POLICY IF EXISTS landlords_scope_select ON landlords;
DROP POLICY IF EXISTS landlords_scope_insert ON landlords;
DROP POLICY IF EXISTS landlords_scope_update ON landlords;
DROP POLICY IF EXISTS landlords_scope_delete ON landlords;

CREATE POLICY landlords_scope_select
ON landlords
FOR SELECT
USING (
    id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY landlords_scope_insert
ON landlords
FOR INSERT
WITH CHECK (
    app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY landlords_scope_update
ON landlords
FOR UPDATE
USING (
    id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
)
WITH CHECK (
    id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY landlords_scope_delete
ON landlords
FOR DELETE
USING (
    app.current_role() IN ('ADMIN', 'SYSTEM')
);


-- ============================================================
-- DIRECT landlord_id TABLES
-- ============================================================

-- ------------------------------------------------------------
-- PROPERTIES
-- ------------------------------------------------------------

DROP POLICY IF EXISTS properties_scope_select ON properties;
DROP POLICY IF EXISTS properties_scope_insert ON properties;
DROP POLICY IF EXISTS properties_scope_update ON properties;
DROP POLICY IF EXISTS properties_scope_delete ON properties;

CREATE POLICY properties_scope_select
ON properties
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY properties_scope_insert
ON properties
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY properties_scope_update
ON properties
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY properties_scope_delete
ON properties
FOR DELETE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);


-- ------------------------------------------------------------
-- UNITS
-- ------------------------------------------------------------

DROP POLICY IF EXISTS units_scope_select ON units;
DROP POLICY IF EXISTS units_scope_insert ON units;
DROP POLICY IF EXISTS units_scope_update ON units;
DROP POLICY IF EXISTS units_scope_delete ON units;

CREATE POLICY units_scope_select
ON units
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY units_scope_insert
ON units
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY units_scope_update
ON units
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY units_scope_delete
ON units
FOR DELETE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);


-- ------------------------------------------------------------
-- TENANTS
-- ------------------------------------------------------------

DROP POLICY IF EXISTS tenants_scope_select ON tenants;
DROP POLICY IF EXISTS tenants_scope_insert ON tenants;
DROP POLICY IF EXISTS tenants_scope_update ON tenants;
DROP POLICY IF EXISTS tenants_scope_delete ON tenants;

CREATE POLICY tenants_scope_select
ON tenants
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY tenants_scope_insert
ON tenants
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY tenants_scope_update
ON tenants
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY tenants_scope_delete
ON tenants
FOR DELETE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);


-- ------------------------------------------------------------
-- INVOICES
-- ------------------------------------------------------------

DROP POLICY IF EXISTS invoices_scope_select ON invoices;
DROP POLICY IF EXISTS invoices_scope_insert ON invoices;
DROP POLICY IF EXISTS invoices_scope_update ON invoices;
DROP POLICY IF EXISTS invoices_scope_delete ON invoices;

CREATE POLICY invoices_scope_select
ON invoices
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY invoices_scope_insert
ON invoices
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY invoices_scope_update
ON invoices
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY invoices_scope_delete
ON invoices
FOR DELETE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);


-- ------------------------------------------------------------
-- LEDGER ENTRIES
-- ------------------------------------------------------------

DROP POLICY IF EXISTS ledger_entries_scope_select ON ledger_entries;
DROP POLICY IF EXISTS ledger_entries_scope_insert ON ledger_entries;
DROP POLICY IF EXISTS ledger_entries_scope_update ON ledger_entries;
DROP POLICY IF EXISTS ledger_entries_scope_delete ON ledger_entries;

CREATE POLICY ledger_entries_scope_select
ON ledger_entries
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY ledger_entries_scope_insert
ON ledger_entries
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY ledger_entries_scope_update
ON ledger_entries
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY ledger_entries_scope_delete
ON ledger_entries
FOR DELETE
USING (
    app.current_role() IN ('ADMIN', 'SYSTEM')
);


-- ------------------------------------------------------------
-- PAYMENT PROCESSING
-- ------------------------------------------------------------

DROP POLICY IF EXISTS payment_processing_scope_select ON payment_processing;
DROP POLICY IF EXISTS payment_processing_scope_insert ON payment_processing;
DROP POLICY IF EXISTS payment_processing_scope_update ON payment_processing;
DROP POLICY IF EXISTS payment_processing_scope_delete ON payment_processing;

CREATE POLICY payment_processing_scope_select
ON payment_processing
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY payment_processing_scope_insert
ON payment_processing
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY payment_processing_scope_update
ON payment_processing
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY payment_processing_scope_delete
ON payment_processing
FOR DELETE
USING (
    app.current_role() IN ('ADMIN', 'SYSTEM')
);


-- ------------------------------------------------------------
-- PAYMENT TRANSACTIONS
-- ------------------------------------------------------------

DROP POLICY IF EXISTS payment_transactions_scope_select ON payment_transactions;
DROP POLICY IF EXISTS payment_transactions_scope_insert ON payment_transactions;
DROP POLICY IF EXISTS payment_transactions_scope_update ON payment_transactions;
DROP POLICY IF EXISTS payment_transactions_scope_delete ON payment_transactions;

CREATE POLICY payment_transactions_scope_select
ON payment_transactions
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY payment_transactions_scope_insert
ON payment_transactions
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY payment_transactions_scope_update
ON payment_transactions
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY payment_transactions_scope_delete
ON payment_transactions
FOR DELETE
USING (
    app.current_role() IN ('ADMIN', 'SYSTEM')
);


-- ------------------------------------------------------------
-- UNASSIGNED PAYMENTS
-- ------------------------------------------------------------

DROP POLICY IF EXISTS unassigned_payments_scope_select ON unassigned_payments;
DROP POLICY IF EXISTS unassigned_payments_scope_insert ON unassigned_payments;
DROP POLICY IF EXISTS unassigned_payments_scope_update ON unassigned_payments;
DROP POLICY IF EXISTS unassigned_payments_scope_delete ON unassigned_payments;

CREATE POLICY unassigned_payments_scope_select
ON unassigned_payments
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY unassigned_payments_scope_insert
ON unassigned_payments
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY unassigned_payments_scope_update
ON unassigned_payments
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY unassigned_payments_scope_delete
ON unassigned_payments
FOR DELETE
USING (
    app.current_role() IN ('ADMIN', 'SYSTEM')
);


-- ------------------------------------------------------------
-- UTILITY READINGS
-- ------------------------------------------------------------

DROP POLICY IF EXISTS utility_readings_scope_select ON utility_readings;
DROP POLICY IF EXISTS utility_readings_scope_insert ON utility_readings;
DROP POLICY IF EXISTS utility_readings_scope_update ON utility_readings;
DROP POLICY IF EXISTS utility_readings_scope_delete ON utility_readings;

CREATE POLICY utility_readings_scope_select
ON utility_readings
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY utility_readings_scope_insert
ON utility_readings
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY utility_readings_scope_update
ON utility_readings
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY utility_readings_scope_delete
ON utility_readings
FOR DELETE
USING (
    app.current_role() IN ('ADMIN', 'SYSTEM')
);


-- ------------------------------------------------------------
-- USER DEVICE TOKENS
-- ------------------------------------------------------------

DROP POLICY IF EXISTS user_device_tokens_scope_select ON user_device_tokens;
DROP POLICY IF EXISTS user_device_tokens_scope_insert ON user_device_tokens;
DROP POLICY IF EXISTS user_device_tokens_scope_update ON user_device_tokens;
DROP POLICY IF EXISTS user_device_tokens_scope_delete ON user_device_tokens;

CREATE POLICY user_device_tokens_scope_select
ON user_device_tokens
FOR SELECT
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY user_device_tokens_scope_insert
ON user_device_tokens
FOR INSERT
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY user_device_tokens_scope_update
ON user_device_tokens
FOR UPDATE
USING (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
)
WITH CHECK (
    landlord_id = app.current_landlord_id()
    OR app.current_role() IN ('ADMIN', 'SYSTEM')
);

CREATE POLICY user_device_tokens_scope_delete
ON user_device_tokens
FOR DELETE
USING (
    app.current_role() IN ('ADMIN', 'SYSTEM')
);


-- ============================================================
-- INDIRECTLY SCOPED TABLES
-- ============================================================

-- ------------------------------------------------------------
-- PAYMENT ALLOCATIONS
-- Scope through both invoice and payment transaction.
-- ------------------------------------------------------------

DROP POLICY IF EXISTS payment_allocations_scope_select ON payment_allocations;
DROP POLICY IF EXISTS payment_allocations_scope_insert ON payment_allocations;
DROP POLICY IF EXISTS payment_allocations_scope_update ON payment_allocations;
DROP POLICY IF EXISTS payment_allocations_scope_delete ON payment_allocations;

CREATE POLICY payment_allocations_scope_select
ON payment_allocations
FOR SELECT
USING (
    app.current_role() IN ('ADMIN', 'SYSTEM')
    OR EXISTS (
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
    app.current_role() IN ('ADMIN', 'SYSTEM')
    OR EXISTS (
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
    app.current_role() IN ('ADMIN', 'SYSTEM')
    OR EXISTS (
        SELECT 1
        FROM payment_transactions pt
        WHERE pt.id = payment_allocations.payment_transaction_id
          AND pt.landlord_id = app.current_landlord_id()
    )
)
WITH CHECK (
    app.current_role() IN ('ADMIN', 'SYSTEM')
    OR EXISTS (
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
    app.current_role() IN ('ADMIN', 'SYSTEM')
);


-- ------------------------------------------------------------
-- PAYMENT CREDITS
-- Scope through payment transaction.
-- ------------------------------------------------------------

DROP POLICY IF EXISTS payment_credits_scope_select ON payment_credits;
DROP POLICY IF EXISTS payment_credits_scope_insert ON payment_credits;
DROP POLICY IF EXISTS payment_credits_scope_update ON payment_credits;
DROP POLICY IF EXISTS payment_credits_scope_delete ON payment_credits;

CREATE POLICY payment_credits_scope_select
ON payment_credits
FOR SELECT
USING (
    app.current_role() IN ('ADMIN', 'SYSTEM')
    OR EXISTS (
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
    app.current_role() IN ('ADMIN', 'SYSTEM')
    OR EXISTS (
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
    app.current_role() IN ('ADMIN', 'SYSTEM')
    OR EXISTS (
        SELECT 1
        FROM payment_transactions pt
        WHERE pt.id = payment_credits.payment_transaction_id
          AND pt.landlord_id = app.current_landlord_id()
    )
)
WITH CHECK (
    app.current_role() IN ('ADMIN', 'SYSTEM')
    OR EXISTS (
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
    app.current_role() IN ('ADMIN', 'SYSTEM')
);


-- ============================================================
-- Force RLS so table owners cannot silently bypass it.
-- We will later move the application to a least-privilege DB role.
-- ============================================================

ALTER TABLE landlords FORCE ROW LEVEL SECURITY;
ALTER TABLE properties FORCE ROW LEVEL SECURITY;
ALTER TABLE units FORCE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
ALTER TABLE invoices FORCE ROW LEVEL SECURITY;
ALTER TABLE ledger_entries FORCE ROW LEVEL SECURITY;
ALTER TABLE payment_processing FORCE ROW LEVEL SECURITY;
ALTER TABLE payment_transactions FORCE ROW LEVEL SECURITY;
ALTER TABLE payment_allocations FORCE ROW LEVEL SECURITY;
ALTER TABLE payment_credits FORCE ROW LEVEL SECURITY;
ALTER TABLE unassigned_payments FORCE ROW LEVEL SECURITY;
ALTER TABLE utility_readings FORCE ROW LEVEL SECURITY;
ALTER TABLE user_device_tokens FORCE ROW LEVEL SECURITY;

COMMIT;

