BEGIN;

-- Migration history used by app.core.migrations and the API startup check.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The API checks for pending migrations at startup through the system role.
GRANT SELECT ON schema_migrations TO kodiflow_system;

COMMIT;
