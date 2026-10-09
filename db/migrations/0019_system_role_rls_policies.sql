BEGIN;

-- Replace the system role's global BYPASSRLS capability with explicit
-- table policies. The system connection remains high-trust and can access
-- every row on these named tables for webhook and background workflows, but
-- does not bypass RLS on future tables by default.

ALTER ROLE kodiflow_system NOBYPASSRLS;

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'landlords',
        'properties',
        'units',
        'tenants',
        'invoices',
        'ledger_entries',
        'payment_processing',
        'payment_transactions',
        'payment_allocations',
        'payment_credits',
        'payment_credit_applications',
        'unassigned_payments',
        'outbox_events',
        'utility_readings',
        'user_device_tokens',
        'app_users',
        'user_memberships'
    ]
    LOOP
        EXECUTE format(
            'DROP POLICY IF EXISTS kodiflow_system_access ON public.%I',
            table_name
        );
        EXECUTE format(
            'CREATE POLICY kodiflow_system_access ON public.%I '
            'FOR ALL TO kodiflow_system USING (true) WITH CHECK (true)',
            table_name
        );
    END LOOP;
END
$$;

COMMIT;
