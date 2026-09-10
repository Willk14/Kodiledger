-- 1. Insert Test Landlord
INSERT INTO landlords (id, full_name, email, phone_number, business_shortcode)
VALUES 
('11111111-1111-1111-1111-111111111111', 'John Kamau', 'kamau@example.com', '254712345678', '123456');

-- 2. Insert Test Property
INSERT INTO properties (id, landlord_id, name, county, town_location, total_units)
VALUES 
('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'Kilimani Heights', 'Nairobi', 'Kilimani', 2);

-- 3. Insert Units
INSERT INTO units (id, property_id, landlord_id, unit_number, base_rent, garbage_fee, water_rate_per_unit, is_occupied)
VALUES 
('33333333-3333-3333-3333-333333333333', '22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'A4', 15000.00, 500.00, 150.00, TRUE),
('44444444-4444-4444-4444-444444444444', '22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'A5', 18000.00, 500.00, 150.00, FALSE);

-- 4. Insert Active Tenant
INSERT INTO tenants (id, landlord_id, unit_id, full_name, primary_phone, lease_start_date, deposit_amount)
VALUES 
('55555555-5555-5555-5555-555555555555', '11111111-1111-1111-1111-111111111111', '33333333-3333-3333-3333-333333333333', 'Mary Wanjiku', '254798765432', '2026-01-01', 15000.00);

-- 5. Insert Invoice
INSERT INTO invoices (id, landlord_id, unit_id, tenant_id, invoice_number, billing_month, rent_amount, garbage_amount, due_date)
VALUES 
('66666666-6666-6666-6666-666666666666', '11111111-1111-1111-1111-111111111111', '33333333-3333-3333-3333-333333333333', '55555555-5555-5555-5555-555555555555', 'INV-202608-A4', '2026-08-01', 15000.00, 500.00, '2026-08-05');

-- 6. Log Invoice in Immutable Ledger (DEBIT Event)
INSERT INTO ledger_entries (landlord_id, unit_id, tenant_id, invoice_id, entry_type, amount, payment_method, status, description)
VALUES 
('11111111-1111-1111-1111-111111111111', '33333333-3333-3333-3333-333333333333', '55555555-5555-5555-5555-555555555555', '66666666-6666-6666-6666-666666666666', 'DEBIT', 15500.00, 'CASH', 'COMPLETED', 'August 2026 Rent & Garbage Invoice');