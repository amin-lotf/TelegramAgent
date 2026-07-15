# Admin dashboard v2 deployment

This is a standalone Compose project. It is intentionally not included by the
repository's application Compose files.

1. Create one read-only PostgreSQL login per service database. Grant only
   `CONNECT`, schema `USAGE`, and table `SELECT`, and set
   `default_transaction_read_only = on` plus a short `statement_timeout`.
2. Copy `admin-dashboard-v2.env.example` to
   `.env.admin_dashboard_v2.docker` and replace every credential/secret.
3. Generate the admin password hash from an environment containing the package:
   `python -m telegram_agent.core.admin_dashboard_v2.security.passwords`.
   Paste the complete generated value into `ADMIN_DASHBOARD_V2_PASSWORD_HASH`.
   The Compose file loads this env file in raw mode so the `$` separators are
   not interpreted as environment-variable references. Quoted values from
   earlier configurations are normalized by the application as well.
4. Ensure the main stack network exists. Override
   `ADMIN_DASHBOARD_V2_DOCKER_NETWORK` when it is not `fatol_fatol-net`.
5. Start only this project:
   `docker compose -f docker/admin_dashboard_v2/admin-dashboard-v2-docker-compose.yml up -d --build`.

For validation or an alternate deployment environment, select another env file
with `ADMIN_DASHBOARD_V2_ENV_FILE`. Its path is resolved relative to this
Compose file.

The default published port is loopback-only at `127.0.0.1:8080`. Terminate TLS
at a reverse proxy before exposing the dashboard beyond the host.
