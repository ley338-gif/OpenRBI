#!/bin/sh
# Segmented-deployment credential scoping (docs/adr/0025-segmented-
# credential-scoping.md). Creates/updates the openrbi_user and
# openrbi_admin Postgres roles and their table/column grants, for an
# operator opting a Segmented deployment into DB role scoping.
#
# This is NOT a docker-entrypoint-initdb.d script: it must run AFTER
# `alembic upgrade head` has created the schema, not at Postgres's own
# first-boot init (which happens before any migration exists) — an
# earlier version of this mechanism tried the initdb.d approach and every
# GRANT failed with "relation does not exist" against a schema-less fresh
# database. Run it exactly where the README's own Quick Start already
# tells you to run migrations:
#
#   docker compose up -d --build
#   docker exec $(docker compose ps -q backend) alembic upgrade head
#   ./scripts/provision-segmented-db-roles.sh
#
# Safe to re-run any time (e.g. after upgrading to a version that adds
# new tables to the allow-list below, or to rotate the two role
# passwords) — every statement is idempotent.
#
# Requires OPENRBI_DB_USER_ROLE_PASSWORD and OPENRBI_DB_ADMIN_ROLE_PASSWORD
# set (in .env, or exported directly) — see .env.example. Does not require
# .env to have OPENRBI_DATABASE_URL_USER/_ADMIN set yet; add those
# afterward, once these roles actually exist, then restart backend-user/
# backend-admin to pick them up.
set -eu

ENV_FILE="${OPENRBI_ENV_FILE:-.env}"
POSTGRES_CONTAINER="${OPENRBI_POSTGRES_CONTAINER:-openrbi-postgres-1}"
POSTGRES_DB_NAME="${POSTGRES_DB:-openrbi}"
POSTGRES_ADMIN_USER="${POSTGRES_USER:-openrbi}"

if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
fi

: "${OPENRBI_DB_USER_ROLE_PASSWORD:?set OPENRBI_DB_USER_ROLE_PASSWORD in $ENV_FILE (see .env.example) before running this script}"
: "${OPENRBI_DB_ADMIN_ROLE_PASSWORD:?set OPENRBI_DB_ADMIN_ROLE_PASSWORD in $ENV_FILE (see .env.example) before running this script}"

echo "[provision-segmented-db-roles] Provisioning openrbi_user/openrbi_admin against $POSTGRES_CONTAINER:$POSTGRES_DB_NAME ..."

# Connects as the existing superuser/owner role (POSTGRES_USER) — the same
# role migrations already run as — never as either scoped role itself.
# Passwords are passed as psql variables (`:'name'`), not raw shell/heredoc
# substitution, so psql itself escapes any embedded quote characters.
docker exec -i \
    -e PGPASSWORD="${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in $ENV_FILE}" \
    "$POSTGRES_CONTAINER" \
    psql -v ON_ERROR_STOP=1 \
         --username "$POSTGRES_ADMIN_USER" \
         --dbname "$POSTGRES_DB_NAME" \
         -v appowner="$POSTGRES_ADMIN_USER" \
         -v dbname="$POSTGRES_DB_NAME" \
         -v admin_pw="$OPENRBI_DB_ADMIN_ROLE_PASSWORD" \
         -v user_pw="$OPENRBI_DB_USER_ROLE_PASSWORD" \
         <<-'EOSQL'
	-- Idempotent: create the role on first run, just update its password
	-- (and re-affirm LOGIN) on a later re-run — a plain CREATE ROLE would
	-- error out with "role already exists" on any re-run otherwise.
	-- psql's :'var' interpolation does not reach inside a dollar-quoted
	-- (DO $$ ... $$) block, so this uses \gexec — a plain top-level SELECT
	-- builds the one right statement as text, then \gexec runs it — rather
	-- than a PL/pgSQL IF/ELSE.
	SELECT format('ALTER ROLE openrbi_admin LOGIN PASSWORD %L', :'admin_pw')
	WHERE EXISTS (SELECT FROM pg_roles WHERE rolname = 'openrbi_admin')
	UNION ALL
	SELECT format('CREATE ROLE openrbi_admin LOGIN PASSWORD %L', :'admin_pw')
	WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'openrbi_admin')
	\gexec

	SELECT format('ALTER ROLE openrbi_user LOGIN PASSWORD %L', :'user_pw')
	WHERE EXISTS (SELECT FROM pg_roles WHERE rolname = 'openrbi_user')
	UNION ALL
	SELECT format('CREATE ROLE openrbi_user LOGIN PASSWORD %L', :'user_pw')
	WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'openrbi_user')
	\gexec

	GRANT CONNECT ON DATABASE :"dbname" TO openrbi_admin, openrbi_user;
	GRANT USAGE ON SCHEMA public TO openrbi_admin, openrbi_user;

	-- openrbi_admin: the same effective privileges the single
	-- pre-existing POSTGRES_USER role has today — full application-data
	-- access, no behavior change for backend-admin, which is already the
	-- intentionally-trusted control-plane role. No blanket DELETE,
	-- matching the append-only audit-log invariant
	-- docs/security-self-assessment.md's V7 section already relies on.
	GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO openrbi_admin;
	-- Applies the same grant automatically to a table a *future* Alembic
	-- migration adds (migrations run as POSTGRES_USER) — without this,
	-- a version upgrade adding a table would silently need this script
	-- re-run by hand just to keep backend-admin working. (It's still
	-- fine, and recommended, to re-run this script after every upgrade
	-- anyway — it's idempotent and this is a belt-and-suspenders default
	-- for tables created before this script's own next run.)
	ALTER DEFAULT PRIVILEGES FOR ROLE :"appowner" IN SCHEMA public
	    GRANT SELECT, INSERT, UPDATE ON TABLES TO openrbi_admin;

	-- openrbi_user: exactly what backend-user's own registered routes
	-- (sessions.py, files.py, display.py) and the *shared* auth/mfa
	-- routes (registered in every listener mode, so they also run inside
	-- a "user"-mode process) actually touch. Deliberately no default
	-- grant for future tables here — an omitted grant fails closed
	-- (permission denied) rather than silently handing a new sensitive
	-- table to the narrow role; re-run this script (after updating it,
	-- if the new table genuinely belongs here) rather than relying on
	-- an automatic default.
	GRANT SELECT, INSERT, UPDATE ON browser_sessions TO openrbi_user;
	GRANT SELECT, INSERT, UPDATE ON quarantine_files TO openrbi_user;
	-- Self-service TOTP recovery codes (app/services/mfa.py): a caller's
	-- own enrollment deletes-and-recreates its set, login consumption
	-- marks one used_at. Not a privilege-escalation surface — fully
	-- user-owned data.
	GRANT SELECT, INSERT, UPDATE, DELETE ON recovery_codes TO openrbi_user;
	GRANT SELECT ON roles TO openrbi_user;
	-- Read-only: display.py resolves which node's Session Agent to
	-- relay to. Enrollment/approval/agent_token_encrypted stay admin-only.
	GRANT SELECT ON browser_nodes TO openrbi_user;
	-- Write the audit trail, never read or rewrite it.
	GRANT INSERT ON security_events TO openrbi_user;
	-- Full-row SELECT is unavoidable: a login must read a candidate row
	-- (including password_hash/totp_secret_encrypted) before it knows
	-- whether the caller is who they claim. UPDATE is restricted to the
	-- genuine self-service columns shared auth.py/mfa.py write on the
	-- *authenticated caller's own* row (change-my-password,
	-- enroll-my-own-MFA) — deliberately NOT role_id/is_active/disabled_at,
	-- and no INSERT at all, so this role can neither create nor
	-- re-privilege any account even via a raw SQL-injection primitive.
	-- See docs/adr/0025's "Interaction with LDAP auto-provisioning"
	-- section: this is why LDAP auto-provisioning is incompatible with
	-- OPENRBI_LISTENER_MODE=user when this scoping is enabled.
	GRANT SELECT ON users TO openrbi_user;
	GRANT UPDATE (password_hash, mfa_enabled, totp_secret_encrypted, updated_at)
	    ON users TO openrbi_user;

	-- No grant at all (openrbi_user cannot even SELECT) on: groups,
	-- user_groups, policies, policy_versions, group_policies,
	-- file_policy_rules, ldap_configs, incidents, worker_metric_samples,
	-- system_state. Postgres's default-deny means simply never granting
	-- these is sufficient — no explicit REVOKE needed on a role that
	-- never received the privilege in the first place.
EOSQL

echo "[provision-segmented-db-roles] Done. Next steps:"
echo "  1. Set OPENRBI_DATABASE_URL_USER/_ADMIN in $ENV_FILE to point at these roles (see .env.example)."
echo "  2. Restart backend-user/backend-admin to pick them up:"
echo "     docker compose -f docker-compose.yml -f docker-compose.segmented.yml up -d backend-user backend-admin"
echo "  3. Verify with: ./scripts/test-segmented-credential-scoping.sh"
