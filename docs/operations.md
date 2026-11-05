# Operations runbook

How the production deployment is set up, deployed, watched and repaired. Written to be followed
step by step. Never paste secrets into chats, issues or commits: they go only into the files and
settings named here.

## 1. What runs where

```
Internet ──443──▶ Caddy (web)  ── static frontend
                       │
                       └─/api/*──▶ API (2 processes) ──▶ PostgreSQL (db)
                                                           ▲
                                   Worker (jobs) ──────────┘
```

- One Ubuntu 24.04 server running Docker Compose (`deploy/compose.prod.yaml`), project `sia-prod`.
- Only Caddy publishes ports (80, 443). It gets and renews the HTTPS certificate by itself.
- Files on the server live in `/opt/sia`:
  - `deploy/compose.prod.yaml`, `deploy/deploy.sh`: copied by every deploy;
  - `deploy/.env.production`: settings and secrets (you create it once; never committed);
  - `deploy/.env`: images of the running release (written by `deploy.sh`; no secrets);
  - `infra/postgres/init/02-create-app-role.sh`: creates the restricted database role.
- Images: `ghcr.io/<owner>/sia-backend:<commit>` and `sia-web:<commit>`, built by GitHub Actions.

## 2. First-time setup

### 2.1 Server

1. Create the server (Ubuntu 24.04 LTS, 4 GB RAM) with your SSH key added. On your first
   `ssh root@<ip>`, compare the host key fingerprint with the one the provider's console shows.
2. Run the setup script (firewall, SSH keys only, automatic updates, Docker, `deploy` user):

   ```bash
   scp deploy/bootstrap-server.sh root@<ip>:/root/
   ssh root@<ip> bash /root/bootstrap-server.sh
   ```

3. From now on log in as `deploy` (`ssh deploy@<ip>`); root login is disabled.

### 2.2 Hostname (DuckDNS)

At duckdns.org, set your subdomain's IP to the server's IP. Check: `nslookup <name>.duckdns.org`
must print the server IP before the first deploy (Caddy needs it to get a certificate).

### 2.3 Settings file on the server

```bash
ssh deploy@<ip>
cd /opt/sia/deploy
nano .env.production        # start from deploy/env.production.example in the repository
chmod 600 .env.production
```

Generate every password with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
Set `SITE_ADDRESS` and `SIA_ALLOWED_ORIGINS` to your hostname, `SENTRY_DSN` to the backend
project's DSN, and `ANTHROPIC_API_KEY` to a production-only key whose monthly spend limit is set
in the Anthropic console (same amount as `SIA_AI_MONTHLY_BUDGET_USD`).

### 2.4 GitHub

A dedicated SSH key lets GitHub Actions log in as `deploy` (and nothing else):

```bash
ssh-keygen -t ed25519 -N "" -C "github-actions-deploy" -f sia_deploy
ssh-copy-id -i sia_deploy.pub deploy@<ip>
ssh-keyscan -t ed25519 <ip> > sia_known_hosts   # compare: ssh-keygen -lf sia_known_hosts

gh api -X PUT "repos/{owner}/{repo}/environments/production"
gh secret set DEPLOY_HOST --env production --body "<ip>"
gh secret set DEPLOY_USER --env production --body "deploy"
gh secret set DEPLOY_SSH_KEY --env production < sia_deploy
gh secret set DEPLOY_KNOWN_HOSTS --env production < sia_known_hosts
gh variable set SITE_ADDRESS --body "<name>.duckdns.org"
gh variable set VITE_SENTRY_DSN --body "<browser project DSN>"   # optional
gh variable set DEPLOY_ENABLED --body "true"

rm sia_deploy   # GitHub has it now; the public half stays on the server
```

Optional but recommended: in the repository settings, Environments → production → Required
reviewers → yourself. Every deploy then waits for your click.

### 2.5 First deploy

Actions → Deploy → Run workflow (or push to main and wait for CI). The workflow builds the
images, deploys and finally checks `https://<site>/api/health/ready`.

### 2.6 Monitoring

- Sentry: keep the default alert ("a new issue is created" → email).
- Uptime: a free monitor (e.g. UptimeRobot) on `https://<site>/api/health/ready`, every 5
  minutes, alerting by email.

## 3. Everyday tasks

| Task | How |
|---|---|
| Deploy | Merge to main; CI passes; Deploy runs (approve it if reviewers are required). |
| Roll back | Actions → Deploy → Run workflow → enter an older commit SHA. Images are reused. Note: database migrations are not rolled back; check the migrations between the two commits first. |
| See what's running | `cd /opt/sia/deploy && docker compose -f compose.prod.yaml ps`; `cat .env` |
| Logs | `docker compose -f compose.prod.yaml logs --since 1h api worker` (JSON lines; search by `request_id` from a Sentry event) |
| AI on/off for a workspace | `docker compose -f compose.prod.yaml run --rm --no-deps api python -m sia.scripts.ai_access --list` (then `--org <id> --on`) |
| Restart everything | `docker compose -f compose.prod.yaml restart` |

A deploy restarts the API while Caddy holds incoming requests (they are slower, not failed),
then restarts Caddy for under a second. Measured locally: 1 failed request out of 217 during an
upgrade.

## 4. When an alert fires

| Alert | First checks |
|---|---|
| Uptime: site down | `docker compose ps` (all `Up`/`healthy`?); `logs --tail 100 web api db`; disk: `df -h`; memory: `free -m`. |
| Sentry: new error | Open the event, note the `request_id` tag, then `logs api worker \| grep <request_id>`. |
| AI features paused | This month's AI budget is used up (Settings → AI usage). Raise `SIA_AI_MONTHLY_BUDGET_USD` deliberately, or wait for the 1st. |
| Certificate problems | `logs web`: DNS must point at the server and ports 80/443 must be open. |

## 5. Rotating secrets

- **Database passwords:** change both in `.env.production`, then:
  `docker compose -f compose.prod.yaml exec db bash /docker-entrypoint-initdb.d/02-create-app-role.sh`
  (app role) and `ALTER ROLE` for the owner via `psql`; then `docker compose ... up -d`.
- **Anthropic key / Sentry DSN:** replace in `.env.production`, then `docker compose ... up -d`.
- **Deploy SSH key:** generate a new pair, add the public key to `/home/deploy/.ssh/authorized_keys`,
  replace `DEPLOY_SSH_KEY`, then remove the old public key from the server.

## 6. Backups and restore

See section 6 after Phase 8e.
