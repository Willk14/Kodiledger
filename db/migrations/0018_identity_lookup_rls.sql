BEGIN;

-- Allow the backend application role to resolve authenticated identities and
-- their KodiLedger memberships. This role is used only by the trusted backend;
-- it cannot modify either table and is not exposed to clients.

ALTER TABLE app_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_memberships ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS app_users_kodiflow_app_read ON app_users;
CREATE POLICY app_users_kodiflow_app_read
ON app_users
FOR SELECT
TO kodiflow_app
USING (true);

DROP POLICY IF EXISTS user_memberships_kodiflow_app_read ON user_memberships;
CREATE POLICY user_memberships_kodiflow_app_read
ON user_memberships
FOR SELECT
TO kodiflow_app
USING (true);

COMMIT;
