-- 1. Custom PostgreSQL ENUM Types for Financial Life Cycle
CREATE TYPE payment_status_enum AS ENUM (
    'INITIATED',
    'PENDING',
    'COMPLETED',
    'FAILED',
    'REVERSED'
);

CREATE TYPE payment_method_enum AS ENUM (
    'MPESA_STK_PUSH',
    'MPESA_C2B_PAYBILL',
    'MPESA_TILL',
    'BANK_TRANSFER',
    'CASH',
    'CHEQUE'
);

CREATE TYPE ledger_entry_type_enum AS ENUM (
    'DEBIT',
    'CREDIT'
);

-- 2. Master Landlords Table
CREATE TABLE landlords (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone_number VARCHAR(15) UNIQUE NOT NULL,
    kra_pin VARCHAR(20),
    business_shortcode VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. Properties Table
CREATE TABLE properties (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    landlord_id UUID NOT NULL REFERENCES landlords(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    county VARCHAR(100) NOT NULL,
    town_location VARCHAR(255),
    total_units INT NOT NULL CHECK (total_units > 0),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_properties_landlord ON properties(landlord_id);

-- 4. Units Table
CREATE TABLE units (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    landlord_id UUID NOT NULL REFERENCES landlords(id) ON DELETE CASCADE,
    unit_number VARCHAR(50) NOT NULL,
    base_rent NUMERIC(12, 2) NOT NULL CHECK (base_rent >= 0),
    garbage_fee NUMERIC(10, 2) DEFAULT 0.00 CHECK (garbage_fee >= 0),
    security_fee NUMERIC(10, 2) DEFAULT 0.00 CHECK (security_fee >= 0),
    water_rate_per_unit NUMERIC(10, 2) DEFAULT 0.00,
    is_occupied BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (property_id, unit_number)
);
CREATE INDEX idx_units_landlord ON units(landlord_id);
CREATE INDEX idx_units_property ON units(property_id);

-- 5. Tenants Table
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    landlord_id UUID NOT NULL REFERENCES landlords(id) ON DELETE CASCADE,
    unit_id UUID NOT NULL REFERENCES units(id) ON DELETE RESTRICT,
    full_name VARCHAR(255) NOT NULL,
    primary_phone VARCHAR(15) NOT NULL,
    id_number VARCHAR(50),
    lease_start_date DATE NOT NULL,
    deposit_amount NUMERIC(12, 2) DEFAULT 0.00,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_tenants_landlord ON tenants(landlord_id);
CREATE INDEX idx_tenants_phone ON tenants(primary_phone);

-- 6. Utility Readings Table
CREATE TABLE utility_readings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    landlord_id UUID NOT NULL REFERENCES landlords(id) ON DELETE CASCADE,
    unit_id UUID NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    reading_month DATE NOT NULL,
    previous_reading NUMERIC(10, 2) NOT NULL,
    current_reading NUMERIC(10, 2) NOT NULL,
    consumption NUMERIC(10, 2) GENERATED ALWAYS AS (current_reading - previous_reading) STORED,
    total_water_cost NUMERIC(12, 2) NOT NULL,
    recorded_by_user_id UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_consumption CHECK (current_reading >= previous_reading)
);

-- 7. Monthly Invoices Table
CREATE TABLE invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    landlord_id UUID NOT NULL REFERENCES landlords(id) ON DELETE CASCADE,
    unit_id UUID NOT NULL REFERENCES units(id) ON DELETE RESTRICT,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    invoice_number VARCHAR(100) UNIQUE NOT NULL,
    billing_month DATE NOT NULL,
    rent_amount NUMERIC(12, 2) NOT NULL,
    water_amount NUMERIC(12, 2) DEFAULT 0.00,
    garbage_amount NUMERIC(10, 2) DEFAULT 0.00,
    security_amount NUMERIC(10, 2) DEFAULT 0.00,
    total_amount NUMERIC(12, 2) GENERATED ALWAYS AS (rent_amount + water_amount + garbage_amount + security_amount) STORED,
    due_date DATE NOT NULL,
    is_paid BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_invoices_landlord ON invoices(landlord_id);
CREATE INDEX idx_invoices_tenant ON invoices(tenant_id);

-- 8. Raw M-Pesa Callback Webhook Audit Table
CREATE TABLE raw_payment_webhooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_provider VARCHAR(50) DEFAULT 'SAFARICOM_DARAJA',
    merchant_request_id VARCHAR(100),
    checkout_request_id VARCHAR(100),
    mpesa_receipt_number VARCHAR(100),
    raw_payload JSONB NOT NULL,
    processed BOOLEAN DEFAULT FALSE,
    error_log TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_raw_webhooks_receipt ON raw_payment_webhooks(mpesa_receipt_number);

-- 9. Immutable Financial Double-Entry Ledger
CREATE TABLE ledger_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    landlord_id UUID NOT NULL REFERENCES landlords(id) ON DELETE CASCADE,
    unit_id UUID NOT NULL REFERENCES units(id) ON DELETE RESTRICT,
    tenant_id UUID REFERENCES tenants(id) ON DELETE RESTRICT,
    invoice_id UUID REFERENCES invoices(id) ON DELETE SET NULL,
    mpesa_receipt_number VARCHAR(100) UNIQUE,
    merchant_request_id VARCHAR(100),
    entry_type ledger_entry_type_enum NOT NULL,
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    payment_method payment_method_enum NOT NULL,
    status payment_status_enum NOT NULL DEFAULT 'INITIATED',
    payer_phone VARCHAR(15),
    payer_name VARCHAR(255),
    account_reference_used VARCHAR(100),
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_ledger_landlord ON ledger_entries(landlord_id);
CREATE INDEX idx_ledger_unit ON ledger_entries(unit_id);
CREATE INDEX idx_ledger_tenant ON ledger_entries(tenant_id);
CREATE INDEX idx_ledger_receipt ON ledger_entries(mpesa_receipt_number);

-- 10. Unassigned Payments Queue (Typo Handling)
CREATE TABLE unassigned_payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    landlord_id UUID NOT NULL REFERENCES landlords(id) ON DELETE CASCADE,
    raw_webhook_id UUID REFERENCES raw_payment_webhooks(id),
    mpesa_receipt_number VARCHAR(100) UNIQUE NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    payer_phone VARCHAR(15) NOT NULL,
    payer_name VARCHAR(255),
    invalid_account_reference VARCHAR(100),
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_unit_id UUID REFERENCES units(id),
    resolved_by_user_id UUID,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_unassigned_landlord ON unassigned_payments(landlord_id);

-- 11. Mobile Push Notification Tokens
CREATE TABLE user_device_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    landlord_id UUID NOT NULL REFERENCES landlords(id) ON DELETE CASCADE,
    device_token TEXT NOT NULL UNIQUE,
    platform VARCHAR(20) NOT NULL,
    last_used_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_device_tokens_landlord ON user_device_tokens(landlord_id);

-- 12. Enable Row-Level Security (RLS)
ALTER TABLE properties ENABLE ROW LEVEL SECURITY;
ALTER TABLE units ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE utility_readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledger_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE unassigned_payments ENABLE ROW LEVEL SECURITY;

CREATE POLICY landlord_properties_policy ON properties
    FOR ALL USING (landlord_id = NULLIF(current_setting('app.current_landlord_id', true), '')::UUID);

CREATE POLICY landlord_units_policy ON units
    FOR ALL USING (landlord_id = NULLIF(current_setting('app.current_landlord_id', true), '')::UUID);

CREATE POLICY landlord_ledger_policy ON ledger_entries
    FOR ALL USING (landlord_id = NULLIF(current_setting('app.current_landlord_id', true), '')::UUID);

-- 13. Dynamic Tenant Balances View
CREATE VIEW tenant_balances_view AS
SELECT 
    t.id AS tenant_id,
    t.landlord_id,
    t.unit_id,
    t.full_name,
    t.primary_phone,
    u.unit_number,
    COALESCE(SUM(CASE WHEN l.entry_type = 'DEBIT' AND l.status = 'COMPLETED' THEN l.amount ELSE 0 END), 0) AS total_debited,
    COALESCE(SUM(CASE WHEN l.entry_type = 'CREDIT' AND l.status = 'COMPLETED' THEN l.amount ELSE 0 END), 0) AS total_credited,
    (
        COALESCE(SUM(CASE WHEN l.entry_type = 'DEBIT' AND l.status = 'COMPLETED' THEN l.amount ELSE 0 END), 0) -
        COALESCE(SUM(CASE WHEN l.entry_type = 'CREDIT' AND l.status = 'COMPLETED' THEN l.amount ELSE 0 END), 0)
    ) AS current_outstanding_balance
FROM tenants t
JOIN units u ON t.unit_id = u.id
LEFT JOIN ledger_entries l ON t.id = l.tenant_id
WHERE t.is_active = TRUE
GROUP BY t.id, t.landlord_id, t.unit_id, t.full_name, t.primary_phone, u.unit_number;