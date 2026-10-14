-- Provider-neutral external identity and KodiLedger-owned authorization mapping.
-- SYSTEM is intentionally excluded: it remains a database/service trust role.

CREATE TABLE app_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    identity_issuer VARCHAR(512) NOT NULL,
    identity_subject VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_app_users_identity UNIQUE (identity_issuer, identity_subject)
);

ALTER TABLE tenants
    ADD CONSTRAINT uq_tenants_id_landlord_id UNIQUE (id, landlord_id);

CREATE TABLE user_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL,
    landlord_id UUID REFERENCES landlords(id) ON DELETE CASCADE,
    tenant_id UUID,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT ck_user_memberships_application_role
        CHECK (role IN ('LANDLORD', 'CARETAKER', 'TENANT', 'ADMIN')),
    CONSTRAINT ck_user_memberships_role_scope CHECK (
        (role IN ('LANDLORD', 'CARETAKER') AND landlord_id IS NOT NULL AND tenant_id IS NULL)
        OR (role = 'TENANT' AND landlord_id IS NOT NULL AND tenant_id IS NOT NULL)
        OR (role = 'ADMIN' AND landlord_id IS NULL AND tenant_id IS NULL)
    ),
    CONSTRAINT fk_user_memberships_tenant_landlord
        FOREIGN KEY (tenant_id, landlord_id) REFERENCES tenants(id, landlord_id)
);

CREATE UNIQUE INDEX uq_user_memberships_landlord_role
    ON user_memberships (user_id, role, landlord_id)
    WHERE role IN ('LANDLORD', 'CARETAKER');
CREATE UNIQUE INDEX uq_user_memberships_tenant
    ON user_memberships (user_id, tenant_id)
    WHERE role = 'TENANT';
CREATE UNIQUE INDEX uq_user_memberships_admin
    ON user_memberships (user_id)
    WHERE role = 'ADMIN';

CREATE INDEX idx_user_memberships_user_active
    ON user_memberships (user_id)
    WHERE is_active = TRUE;

-- User-facing authentication can resolve identity and membership but cannot
-- self-enroll, assign roles, or change tenant scope.
GRANT SELECT ON TABLE app_users, user_memberships TO kodiflow_app;
