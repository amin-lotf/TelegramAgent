# Admin dashboard

Read-only operational UI for tracing Telegram message lifecycles across service databases.

## Run

1. Copy and fill env:

```bash
cp docker/admin_dashboard/.env.admin_dashboard.docker.example \
   docker/admin_dashboard/.env.admin_dashboard.docker
```

2. From the repository root (project already includes this compose file):

```bash
docker compose up -d --build admin-dashboard
```

3. Open http://127.0.0.1:8010/login

Local Docker Compose creates the `telegram` user; the example env uses that so the dashboard works after `make setup`.

## Read-only database roles (recommended for shared/staging/production)

On each service Postgres, create a role that can only `SELECT`:

```sql
CREATE ROLE dashboard_ro LOGIN PASSWORD '…';
GRANT CONNECT ON DATABASE telegram_agent TO dashboard_ro;
GRANT USAGE ON SCHEMA public TO dashboard_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dashboard_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO dashboard_ro;
```

Point the `*_RO_DATABASE_URL` variables at that role.

## Notes

- The dashboard never writes to service databases.
- Message details include a **Workflows** tab that correlates generated content work
  through agent-runtime and refreshes active workflow stages automatically.
- `WORKFLOW_POLL_INTERVAL_SECONDS` controls detail-view refresh frequency; the
  sidebar workflow badges refresh on normal navigation or page reload.
- Agent-runtime pipeline: rule-based message grouping → download agent → content-processing handoff (intent classification removed).
- Every settings field must appear in `.env.admin_dashboard.docker.example`.
