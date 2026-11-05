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
  - `deploy/compose.prod.yaml`, `deploy.sh`, `backup.sh`, `restore.sh`: copied by every deploy;
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

**What:** every night `deploy/backup.sh` dumps the whole database (all organisations), encrypts
it to a GPG **public** key and keeps 7 daily + 4 weekly copies in `/opt/sia/backups`. The
server cannot read its own backups: the private key lives only with you, offline.
**A backup only counts once it has been restored**, so the drill (6.3) is part of the job.

### 6.1 One-time setup

On **your own computer** (not the server):

```bash
gpg --quick-gen-key "SIA backups <you@example.com>" default default never
gpg --armor --export you@example.com > backup-public.asc
gpg --armor --export-secret-keys you@example.com > backup-PRIVATE.asc
```

Store `backup-PRIVATE.asc` and its passphrase somewhere safe and **off the server** (password
manager plus an offline copy). Without it the backups are useless.

On the server:

```bash
scp backup-public.asc deploy@<ip>:/tmp/ && ssh deploy@<ip>
gpg --import /tmp/backup-public.asc && rm /tmp/backup-public.asc
cd /opt/sia/deploy
cp backup.env.example backup.env && nano backup.env   # set BACKUP_GPG_RECIPIENT
./backup.sh                                            # first backup, by hand
crontab -e   # add:  15 3 * * * /opt/sia/deploy/backup.sh >> /opt/sia/backups/backup.log 2>&1
```

Recommended: a heartbeat check (e.g. healthchecks.io, free) in `BACKUP_PING_URL`, so you get an
email when a night's backup does not happen; and an off-server copy (`BACKUP_REMOTE` with
rclone, e.g. a Backblaze B2 or Hetzner Storage Box bucket), so losing the server does not lose
the backups. The deploy scripts copy `backup.sh`/`restore.sh` only if you copy them: run
`scp deploy/backup.sh deploy/restore.sh deploy@<ip>:/opt/sia/deploy/` after changes.

### 6.2 Restoring (disaster recovery)

The private key must be in the GPG keyring of whoever restores. Import it only for the restore:

```bash
gpg --import backup-PRIVATE.asc
/opt/sia/deploy/restore.sh replace /opt/sia/backups/daily/sia-<time>.dump.gpg
gpg --delete-secret-keys you@example.com     # afterwards: the server must not keep it
```

`replace` first restores into a separate database and checks it (schema version, tables,
row-level security, row counts); only then it stops the app, swaps the databases and starts
the app again. Anything written after the backup is lost. If the whole server is lost: set up a
new one (section 2), deploy, copy the backup from the off-server copy, then restore as above.

### 6.3 Monthly restore drill

```bash
/opt/sia/deploy/restore.sh verify /opt/sia/backups/daily/<newest>.dump.gpg
```

`verify` restores into a scratch database next to production, runs the same checks, prints
the row counts and deletes the scratch database again; production is not touched. (It needs
the private key too: import it for the drill and delete it afterwards, as above.)

**Drill log** (append a line each time):

| Date | Backup | Result |
|---|---|---|
| 2026-11-05 | local production stack, sample data | `verify` passed (schema ecf4f8eecb83, RLS on 13 tables, 12 companies); `replace` after deleting all companies restored 12 companies, app served them via the restricted role |
