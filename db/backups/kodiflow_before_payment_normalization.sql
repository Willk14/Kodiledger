--
-- PostgreSQL database dump
--

\restrict hjnui1VPzLA2ZLd4uwbW9fUnpkkkQza9T5sCfAANXVniqu2lcfzf6d3uj9B2LuR

-- Dumped from database version 15.19
-- Dumped by pg_dump version 15.19

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: ledger_entry_type_enum; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.ledger_entry_type_enum AS ENUM (
    'DEBIT',
    'CREDIT'
);


ALTER TYPE public.ledger_entry_type_enum OWNER TO postgres;

--
-- Name: payment_method_enum; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.payment_method_enum AS ENUM (
    'MPESA_STK_PUSH',
    'MPESA_C2B_PAYBILL',
    'MPESA_TILL',
    'BANK_TRANSFER',
    'CASH',
    'CHEQUE'
);


ALTER TYPE public.payment_method_enum OWNER TO postgres;

--
-- Name: payment_status_enum; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.payment_status_enum AS ENUM (
    'INITIATED',
    'PENDING',
    'COMPLETED',
    'FAILED',
    'REVERSED'
);


ALTER TYPE public.payment_status_enum OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: invoices; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.invoices (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    landlord_id uuid NOT NULL,
    unit_id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    invoice_number character varying(100) NOT NULL,
    billing_month date NOT NULL,
    rent_amount numeric(12,2) NOT NULL,
    water_amount numeric(12,2) DEFAULT 0.00,
    garbage_amount numeric(10,2) DEFAULT 0.00,
    security_amount numeric(10,2) DEFAULT 0.00,
    total_amount numeric(12,2) GENERATED ALWAYS AS ((((rent_amount + water_amount) + garbage_amount) + security_amount)) STORED,
    due_date date NOT NULL,
    is_paid boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.invoices OWNER TO postgres;

--
-- Name: landlords; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.landlords (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    full_name character varying(255) NOT NULL,
    email character varying(255) NOT NULL,
    phone_number character varying(15) NOT NULL,
    kra_pin character varying(20),
    business_shortcode character varying(20),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.landlords OWNER TO postgres;

--
-- Name: ledger_entries; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ledger_entries (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    landlord_id uuid NOT NULL,
    unit_id uuid NOT NULL,
    tenant_id uuid,
    invoice_id uuid,
    mpesa_receipt_number character varying(100),
    merchant_request_id character varying(100),
    entry_type public.ledger_entry_type_enum NOT NULL,
    amount numeric(12,2) NOT NULL,
    payment_method public.payment_method_enum NOT NULL,
    status public.payment_status_enum DEFAULT 'INITIATED'::public.payment_status_enum NOT NULL,
    payer_phone character varying(15),
    payer_name character varying(255),
    account_reference_used character varying(100),
    description text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ledger_entries_amount_check CHECK ((amount > (0)::numeric))
);


ALTER TABLE public.ledger_entries OWNER TO postgres;

--
-- Name: payment_processing; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.payment_processing (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    mpesa_receipt_number character varying(100) NOT NULL,
    raw_webhook_id uuid NOT NULL,
    landlord_id uuid NOT NULL,
    status character varying(20) NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    processed_at timestamp with time zone,
    CONSTRAINT chk_payment_processing_status CHECK (((status)::text = ANY ((ARRAY['PROCESSING'::character varying, 'COMPLETED'::character varying, 'FAILED'::character varying, 'UNASSIGNED'::character varying])::text[])))
);


ALTER TABLE public.payment_processing OWNER TO postgres;

--
-- Name: properties; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.properties (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    landlord_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    county character varying(100) NOT NULL,
    town_location character varying(255),
    total_units integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT properties_total_units_check CHECK ((total_units > 0))
);


ALTER TABLE public.properties OWNER TO postgres;

--
-- Name: raw_payment_webhooks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.raw_payment_webhooks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_provider character varying(50) DEFAULT 'SAFARICOM_DARAJA'::character varying,
    merchant_request_id character varying(100),
    checkout_request_id character varying(100),
    mpesa_receipt_number character varying(100),
    raw_payload jsonb NOT NULL,
    processed boolean DEFAULT false,
    error_log text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.raw_payment_webhooks OWNER TO postgres;

--
-- Name: tenants; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tenants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    landlord_id uuid NOT NULL,
    unit_id uuid NOT NULL,
    full_name character varying(255) NOT NULL,
    primary_phone character varying(15) NOT NULL,
    id_number character varying(50),
    lease_start_date date NOT NULL,
    deposit_amount numeric(12,2) DEFAULT 0.00,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.tenants OWNER TO postgres;

--
-- Name: units; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.units (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    property_id uuid NOT NULL,
    landlord_id uuid NOT NULL,
    unit_number character varying(50) NOT NULL,
    base_rent numeric(12,2) NOT NULL,
    garbage_fee numeric(10,2) DEFAULT 0.00,
    security_fee numeric(10,2) DEFAULT 0.00,
    water_rate_per_unit numeric(10,2) DEFAULT 0.00,
    is_occupied boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT units_base_rent_check CHECK ((base_rent >= (0)::numeric)),
    CONSTRAINT units_garbage_fee_check CHECK ((garbage_fee >= (0)::numeric)),
    CONSTRAINT units_security_fee_check CHECK ((security_fee >= (0)::numeric))
);


ALTER TABLE public.units OWNER TO postgres;

--
-- Name: tenant_balances_view; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.tenant_balances_view AS
 SELECT t.id AS tenant_id,
    t.landlord_id,
    t.unit_id,
    t.full_name,
    t.primary_phone,
    u.unit_number,
    COALESCE(sum(
        CASE
            WHEN ((l.entry_type = 'DEBIT'::public.ledger_entry_type_enum) AND (l.status = 'COMPLETED'::public.payment_status_enum)) THEN l.amount
            ELSE (0)::numeric
        END), (0)::numeric) AS total_debited,
    COALESCE(sum(
        CASE
            WHEN ((l.entry_type = 'CREDIT'::public.ledger_entry_type_enum) AND (l.status = 'COMPLETED'::public.payment_status_enum)) THEN l.amount
            ELSE (0)::numeric
        END), (0)::numeric) AS total_credited,
    (COALESCE(sum(
        CASE
            WHEN ((l.entry_type = 'DEBIT'::public.ledger_entry_type_enum) AND (l.status = 'COMPLETED'::public.payment_status_enum)) THEN l.amount
            ELSE (0)::numeric
        END), (0)::numeric) - COALESCE(sum(
        CASE
            WHEN ((l.entry_type = 'CREDIT'::public.ledger_entry_type_enum) AND (l.status = 'COMPLETED'::public.payment_status_enum)) THEN l.amount
            ELSE (0)::numeric
        END), (0)::numeric)) AS current_outstanding_balance
   FROM ((public.tenants t
     JOIN public.units u ON ((t.unit_id = u.id)))
     LEFT JOIN public.ledger_entries l ON ((t.id = l.tenant_id)))
  WHERE (t.is_active = true)
  GROUP BY t.id, t.landlord_id, t.unit_id, t.full_name, t.primary_phone, u.unit_number;


ALTER TABLE public.tenant_balances_view OWNER TO postgres;

--
-- Name: unassigned_payments; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.unassigned_payments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    landlord_id uuid NOT NULL,
    raw_webhook_id uuid,
    mpesa_receipt_number character varying(100) NOT NULL,
    amount numeric(12,2) NOT NULL,
    payer_phone character varying(15) NOT NULL,
    payer_name character varying(255),
    invalid_account_reference character varying(100),
    is_resolved boolean DEFAULT false,
    resolved_unit_id uuid,
    resolved_by_user_id uuid,
    resolved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.unassigned_payments OWNER TO postgres;

--
-- Name: user_device_tokens; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_device_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    landlord_id uuid NOT NULL,
    device_token text NOT NULL,
    platform character varying(20) NOT NULL,
    last_used_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.user_device_tokens OWNER TO postgres;

--
-- Name: utility_readings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.utility_readings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    landlord_id uuid NOT NULL,
    unit_id uuid NOT NULL,
    reading_month date NOT NULL,
    previous_reading numeric(10,2) NOT NULL,
    current_reading numeric(10,2) NOT NULL,
    consumption numeric(10,2) GENERATED ALWAYS AS ((current_reading - previous_reading)) STORED,
    total_water_cost numeric(12,2) NOT NULL,
    recorded_by_user_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_consumption CHECK ((current_reading >= previous_reading))
);


ALTER TABLE public.utility_readings OWNER TO postgres;

--
-- Data for Name: invoices; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.invoices (id, landlord_id, unit_id, tenant_id, invoice_number, billing_month, rent_amount, water_amount, garbage_amount, security_amount, due_date, is_paid, created_at) FROM stdin;
66666666-6666-6666-6666-666666666666	11111111-1111-1111-1111-111111111111	33333333-3333-3333-3333-333333333333	55555555-5555-5555-5555-555555555555	INV-202608-A4	2026-08-01	15000.00	0.00	500.00	0.00	2026-08-05	f	2026-09-11 05:16:42.909271+00
\.


--
-- Data for Name: landlords; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.landlords (id, full_name, email, phone_number, kra_pin, business_shortcode, created_at, updated_at) FROM stdin;
11111111-1111-1111-1111-111111111111	John Kamau	kamau@example.com	254712345678	\N	174379	2026-09-11 05:16:42.864618+00	2026-09-11 05:16:42.864618+00
\.


--
-- Data for Name: ledger_entries; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.ledger_entries (id, landlord_id, unit_id, tenant_id, invoice_id, mpesa_receipt_number, merchant_request_id, entry_type, amount, payment_method, status, payer_phone, payer_name, account_reference_used, description, created_at) FROM stdin;
698fabe3-6333-42d6-9744-92631163319d	11111111-1111-1111-1111-111111111111	33333333-3333-3333-3333-333333333333	55555555-5555-5555-5555-555555555555	66666666-6666-6666-6666-666666666666	\N	\N	DEBIT	15500.00	CASH	COMPLETED	\N	\N	\N	August 2026 Rent & Garbage Invoice	2026-09-11 05:16:42.916832+00
14374e9f-752a-484f-a484-c2714a286c04	11111111-1111-1111-1111-111111111111	33333333-3333-3333-3333-333333333333	55555555-5555-5555-5555-555555555555	\N	SYNTHREC005	SYNTH-MERCHANT-005	CREDIT	1250.00	MPESA_STK_PUSH	COMPLETED	254798765432	\N	\N	M-Pesa STK Push Payment - Receipt: SYNTHREC005	2026-09-11 05:21:12.571943+00
\.


--
-- Data for Name: payment_processing; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.payment_processing (id, mpesa_receipt_number, raw_webhook_id, landlord_id, status, created_at, processed_at) FROM stdin;
3d919b90-874e-47d1-a896-65430379150e	SYNTHREC005	e935ac08-0033-4c90-9c28-4d1f7aadc822	11111111-1111-1111-1111-111111111111	COMPLETED	2026-09-11 05:21:12.571943+00	2026-09-11 05:21:12.571943+00
\.


--
-- Data for Name: properties; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.properties (id, landlord_id, name, county, town_location, total_units, created_at) FROM stdin;
22222222-2222-2222-2222-222222222222	11111111-1111-1111-1111-111111111111	Kilimani Heights	Nairobi	Kilimani	2	2026-09-11 05:16:42.871573+00
\.


--
-- Data for Name: raw_payment_webhooks; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.raw_payment_webhooks (id, source_provider, merchant_request_id, checkout_request_id, mpesa_receipt_number, raw_payload, processed, error_log, created_at) FROM stdin;
e935ac08-0033-4c90-9c28-4d1f7aadc822	SAFARICOM_DARAJA	SYNTH-MERCHANT-005	SYNTH-CHECKOUT-005	SYNTHREC005	{"Body": {"stkCallback": {"ResultCode": 0, "ResultDesc": "The service request is processed successfully.", "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": 1250}, {"Name": "MpesaReceiptNumber", "Value": "SYNTHREC005"}, {"Name": "TransactionDate", "Value": 20260911075000}, {"Name": "PhoneNumber", "Value": 254798765432}]}, "CheckoutRequestID": "SYNTH-CHECKOUT-005", "MerchantRequestID": "SYNTH-MERCHANT-005"}}}	t	\N	2026-09-11 05:21:12.571943+00
ac1a003c-deea-4cfc-8adc-6c1d93d11222	SAFARICOM_DARAJA	SYNTH-MERCHANT-005	SYNTH-CHECKOUT-005	SYNTHREC005	{"Body": {"stkCallback": {"ResultCode": 0, "ResultDesc": "The service request is processed successfully.", "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": 1250}, {"Name": "MpesaReceiptNumber", "Value": "SYNTHREC005"}, {"Name": "TransactionDate", "Value": 20260911075000}, {"Name": "PhoneNumber", "Value": 254798765432}]}, "CheckoutRequestID": "SYNTH-CHECKOUT-005", "MerchantRequestID": "SYNTH-MERCHANT-005"}}}	t	\N	2026-09-11 05:22:12.639414+00
606941d0-0933-41d0-8549-8c6f10fbfd88	SAFARICOM_DARAJA	SYNTH-MERCHANT-005	SYNTH-CHECKOUT-005	SYNTHREC005	{"Body": {"stkCallback": {"ResultCode": 0, "ResultDesc": "The service request is processed successfully.", "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": 1250}, {"Name": "MpesaReceiptNumber", "Value": "SYNTHREC005"}, {"Name": "TransactionDate", "Value": 20260911075000}, {"Name": "PhoneNumber", "Value": 254798765432}]}, "CheckoutRequestID": "SYNTH-CHECKOUT-005", "MerchantRequestID": "SYNTH-MERCHANT-005"}}}	t	\N	2026-09-11 05:24:08.409246+00
\.


--
-- Data for Name: tenants; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.tenants (id, landlord_id, unit_id, full_name, primary_phone, id_number, lease_start_date, deposit_amount, is_active, created_at) FROM stdin;
55555555-5555-5555-5555-555555555555	11111111-1111-1111-1111-111111111111	33333333-3333-3333-3333-333333333333	Mary Wanjiku	254798765432	\N	2026-01-01	15000.00	t	2026-09-11 05:16:42.898657+00
\.


--
-- Data for Name: unassigned_payments; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.unassigned_payments (id, landlord_id, raw_webhook_id, mpesa_receipt_number, amount, payer_phone, payer_name, invalid_account_reference, is_resolved, resolved_unit_id, resolved_by_user_id, resolved_at, created_at) FROM stdin;
\.


--
-- Data for Name: units; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.units (id, property_id, landlord_id, unit_number, base_rent, garbage_fee, security_fee, water_rate_per_unit, is_occupied, created_at) FROM stdin;
33333333-3333-3333-3333-333333333333	22222222-2222-2222-2222-222222222222	11111111-1111-1111-1111-111111111111	A4	15000.00	500.00	0.00	150.00	t	2026-09-11 05:16:42.883818+00
44444444-4444-4444-4444-444444444444	22222222-2222-2222-2222-222222222222	11111111-1111-1111-1111-111111111111	A5	18000.00	500.00	0.00	150.00	f	2026-09-11 05:16:42.883818+00
\.


--
-- Data for Name: user_device_tokens; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.user_device_tokens (id, landlord_id, device_token, platform, last_used_at) FROM stdin;
\.


--
-- Data for Name: utility_readings; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.utility_readings (id, landlord_id, unit_id, reading_month, previous_reading, current_reading, total_water_cost, recorded_by_user_id, created_at) FROM stdin;
\.


--
-- Name: invoices invoices_invoice_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_invoice_number_key UNIQUE (invoice_number);


--
-- Name: invoices invoices_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_pkey PRIMARY KEY (id);


--
-- Name: landlords landlords_email_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.landlords
    ADD CONSTRAINT landlords_email_key UNIQUE (email);


--
-- Name: landlords landlords_phone_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.landlords
    ADD CONSTRAINT landlords_phone_number_key UNIQUE (phone_number);


--
-- Name: landlords landlords_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.landlords
    ADD CONSTRAINT landlords_pkey PRIMARY KEY (id);


--
-- Name: ledger_entries ledger_entries_mpesa_receipt_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ledger_entries
    ADD CONSTRAINT ledger_entries_mpesa_receipt_number_key UNIQUE (mpesa_receipt_number);


--
-- Name: ledger_entries ledger_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ledger_entries
    ADD CONSTRAINT ledger_entries_pkey PRIMARY KEY (id);


--
-- Name: payment_processing payment_processing_mpesa_receipt_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_processing
    ADD CONSTRAINT payment_processing_mpesa_receipt_number_key UNIQUE (mpesa_receipt_number);


--
-- Name: payment_processing payment_processing_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_processing
    ADD CONSTRAINT payment_processing_pkey PRIMARY KEY (id);


--
-- Name: properties properties_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.properties
    ADD CONSTRAINT properties_pkey PRIMARY KEY (id);


--
-- Name: raw_payment_webhooks raw_payment_webhooks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.raw_payment_webhooks
    ADD CONSTRAINT raw_payment_webhooks_pkey PRIMARY KEY (id);


--
-- Name: tenants tenants_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_pkey PRIMARY KEY (id);


--
-- Name: unassigned_payments unassigned_payments_mpesa_receipt_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unassigned_payments
    ADD CONSTRAINT unassigned_payments_mpesa_receipt_number_key UNIQUE (mpesa_receipt_number);


--
-- Name: unassigned_payments unassigned_payments_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unassigned_payments
    ADD CONSTRAINT unassigned_payments_pkey PRIMARY KEY (id);


--
-- Name: units units_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.units
    ADD CONSTRAINT units_pkey PRIMARY KEY (id);


--
-- Name: units units_property_id_unit_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.units
    ADD CONSTRAINT units_property_id_unit_number_key UNIQUE (property_id, unit_number);


--
-- Name: user_device_tokens user_device_tokens_device_token_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_device_tokens
    ADD CONSTRAINT user_device_tokens_device_token_key UNIQUE (device_token);


--
-- Name: user_device_tokens user_device_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_device_tokens
    ADD CONSTRAINT user_device_tokens_pkey PRIMARY KEY (id);


--
-- Name: utility_readings utility_readings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.utility_readings
    ADD CONSTRAINT utility_readings_pkey PRIMARY KEY (id);


--
-- Name: idx_device_tokens_landlord; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_device_tokens_landlord ON public.user_device_tokens USING btree (landlord_id);


--
-- Name: idx_invoices_landlord; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_invoices_landlord ON public.invoices USING btree (landlord_id);


--
-- Name: idx_invoices_tenant; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_invoices_tenant ON public.invoices USING btree (tenant_id);


--
-- Name: idx_ledger_landlord; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ledger_landlord ON public.ledger_entries USING btree (landlord_id);


--
-- Name: idx_ledger_receipt; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ledger_receipt ON public.ledger_entries USING btree (mpesa_receipt_number);


--
-- Name: idx_ledger_tenant; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ledger_tenant ON public.ledger_entries USING btree (tenant_id);


--
-- Name: idx_ledger_unit; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ledger_unit ON public.ledger_entries USING btree (unit_id);


--
-- Name: idx_payment_processing_landlord; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_payment_processing_landlord ON public.payment_processing USING btree (landlord_id);


--
-- Name: idx_payment_processing_receipt; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_payment_processing_receipt ON public.payment_processing USING btree (mpesa_receipt_number);


--
-- Name: idx_payment_processing_webhook; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_payment_processing_webhook ON public.payment_processing USING btree (raw_webhook_id);


--
-- Name: idx_properties_landlord; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_properties_landlord ON public.properties USING btree (landlord_id);


--
-- Name: idx_raw_webhooks_receipt; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_raw_webhooks_receipt ON public.raw_payment_webhooks USING btree (mpesa_receipt_number);


--
-- Name: idx_tenants_landlord; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tenants_landlord ON public.tenants USING btree (landlord_id);


--
-- Name: idx_tenants_phone; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tenants_phone ON public.tenants USING btree (primary_phone);


--
-- Name: idx_unassigned_landlord; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_unassigned_landlord ON public.unassigned_payments USING btree (landlord_id);


--
-- Name: idx_units_landlord; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_units_landlord ON public.units USING btree (landlord_id);


--
-- Name: idx_units_property; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_units_property ON public.units USING btree (property_id);


--
-- Name: invoices invoices_landlord_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_landlord_id_fkey FOREIGN KEY (landlord_id) REFERENCES public.landlords(id) ON DELETE CASCADE;


--
-- Name: invoices invoices_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE RESTRICT;


--
-- Name: invoices invoices_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_unit_id_fkey FOREIGN KEY (unit_id) REFERENCES public.units(id) ON DELETE RESTRICT;


--
-- Name: ledger_entries ledger_entries_invoice_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ledger_entries
    ADD CONSTRAINT ledger_entries_invoice_id_fkey FOREIGN KEY (invoice_id) REFERENCES public.invoices(id) ON DELETE SET NULL;


--
-- Name: ledger_entries ledger_entries_landlord_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ledger_entries
    ADD CONSTRAINT ledger_entries_landlord_id_fkey FOREIGN KEY (landlord_id) REFERENCES public.landlords(id) ON DELETE CASCADE;


--
-- Name: ledger_entries ledger_entries_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ledger_entries
    ADD CONSTRAINT ledger_entries_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE RESTRICT;


--
-- Name: ledger_entries ledger_entries_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ledger_entries
    ADD CONSTRAINT ledger_entries_unit_id_fkey FOREIGN KEY (unit_id) REFERENCES public.units(id) ON DELETE RESTRICT;


--
-- Name: payment_processing payment_processing_landlord_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_processing
    ADD CONSTRAINT payment_processing_landlord_id_fkey FOREIGN KEY (landlord_id) REFERENCES public.landlords(id) ON DELETE CASCADE;


--
-- Name: payment_processing payment_processing_raw_webhook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.payment_processing
    ADD CONSTRAINT payment_processing_raw_webhook_id_fkey FOREIGN KEY (raw_webhook_id) REFERENCES public.raw_payment_webhooks(id) ON DELETE RESTRICT;


--
-- Name: properties properties_landlord_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.properties
    ADD CONSTRAINT properties_landlord_id_fkey FOREIGN KEY (landlord_id) REFERENCES public.landlords(id) ON DELETE CASCADE;


--
-- Name: tenants tenants_landlord_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_landlord_id_fkey FOREIGN KEY (landlord_id) REFERENCES public.landlords(id) ON DELETE CASCADE;


--
-- Name: tenants tenants_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_unit_id_fkey FOREIGN KEY (unit_id) REFERENCES public.units(id) ON DELETE RESTRICT;


--
-- Name: unassigned_payments unassigned_payments_landlord_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unassigned_payments
    ADD CONSTRAINT unassigned_payments_landlord_id_fkey FOREIGN KEY (landlord_id) REFERENCES public.landlords(id) ON DELETE CASCADE;


--
-- Name: unassigned_payments unassigned_payments_raw_webhook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unassigned_payments
    ADD CONSTRAINT unassigned_payments_raw_webhook_id_fkey FOREIGN KEY (raw_webhook_id) REFERENCES public.raw_payment_webhooks(id);


--
-- Name: unassigned_payments unassigned_payments_resolved_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unassigned_payments
    ADD CONSTRAINT unassigned_payments_resolved_unit_id_fkey FOREIGN KEY (resolved_unit_id) REFERENCES public.units(id);


--
-- Name: units units_landlord_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.units
    ADD CONSTRAINT units_landlord_id_fkey FOREIGN KEY (landlord_id) REFERENCES public.landlords(id) ON DELETE CASCADE;


--
-- Name: units units_property_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.units
    ADD CONSTRAINT units_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;


--
-- Name: user_device_tokens user_device_tokens_landlord_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_device_tokens
    ADD CONSTRAINT user_device_tokens_landlord_id_fkey FOREIGN KEY (landlord_id) REFERENCES public.landlords(id) ON DELETE CASCADE;


--
-- Name: utility_readings utility_readings_landlord_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.utility_readings
    ADD CONSTRAINT utility_readings_landlord_id_fkey FOREIGN KEY (landlord_id) REFERENCES public.landlords(id) ON DELETE CASCADE;


--
-- Name: utility_readings utility_readings_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.utility_readings
    ADD CONSTRAINT utility_readings_unit_id_fkey FOREIGN KEY (unit_id) REFERENCES public.units(id) ON DELETE CASCADE;


--
-- Name: invoices; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.invoices ENABLE ROW LEVEL SECURITY;

--
-- Name: ledger_entries landlord_ledger_policy; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY landlord_ledger_policy ON public.ledger_entries USING ((landlord_id = (NULLIF(current_setting('app.current_landlord_id'::text, true), ''::text))::uuid));


--
-- Name: properties landlord_properties_policy; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY landlord_properties_policy ON public.properties USING ((landlord_id = (NULLIF(current_setting('app.current_landlord_id'::text, true), ''::text))::uuid));


--
-- Name: units landlord_units_policy; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY landlord_units_policy ON public.units USING ((landlord_id = (NULLIF(current_setting('app.current_landlord_id'::text, true), ''::text))::uuid));


--
-- Name: ledger_entries; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.ledger_entries ENABLE ROW LEVEL SECURITY;

--
-- Name: properties; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.properties ENABLE ROW LEVEL SECURITY;

--
-- Name: tenants; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;

--
-- Name: unassigned_payments; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.unassigned_payments ENABLE ROW LEVEL SECURITY;

--
-- Name: units; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.units ENABLE ROW LEVEL SECURITY;

--
-- Name: utility_readings; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.utility_readings ENABLE ROW LEVEL SECURITY;

--
-- PostgreSQL database dump complete
--

\unrestrict hjnui1VPzLA2ZLd4uwbW9fUnpkkkQza9T5sCfAANXVniqu2lcfzf6d3uj9B2LuR

