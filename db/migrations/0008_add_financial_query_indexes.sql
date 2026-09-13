CREATE INDEX IF NOT EXISTS idx_invoices_tenant_unpaid_order
ON invoices (
    tenant_id,
    is_paid,
    billing_month,
    created_at
);

CREATE INDEX IF NOT EXISTS idx_payment_allocations_invoice_status
ON payment_allocations (
    invoice_id,
    status
);
