# Security

Threat model, the controls that answer it, the results of the Phase 8 review, and the risks
deliberately accepted. To report a vulnerability, open a private security advisory on GitHub
(Security → Report a vulnerability), not a public issue.

## 1. What we protect

| Asset | Why it matters |
|---|---|
| Customers' company lists, contacts and notes | Commercially sensitive; contacts are personal data |
| Isolation between organisations | One customer must never see another's data |
| Accounts and sessions | Taking over an account exposes all of the above |
| The operator's money | AI calls are paid per use |
| Availability of the service | It's a demo, but it should stay up |

## 2. Who might attack, and how

| Actor | Likely goals |
|---|---|
| Anonymous internet user | Enumerate accounts, guess passwords, run up AI costs, find a crash or a leak |
| Logged-in user of another organisation | Read or change data of an organisation they don't belong to |
| Member of an organisation | Do admin-only things (change the ICP, delete companies) |
| A hostile website being enriched | Make our server fetch internal addresses (SSRF), or steer the AI (prompt injection) |
| Supply chain | A compromised dependency, base image or CI action |

Trust boundaries: browser → Caddy → API (→ worker via the job queue) → PostgreSQL; worker →
public websites and the Anthropic API; CI → container registry → server.

## 3. Threats and controls

| Threat | Controls | Where |
|---|---|---|
| Cross-tenant data access | Forced Row-Level Security on every tenant table, runtime role without BYPASSRLS, composite foreign keys; a guard test fails if a tenant table lacks RLS; tests try cross-tenant reads/writes | ADR-0004/0007, `test_tenant_isolation.py` |
| Anonymous access to the API | Every operation except health/signup/login/logout requires a session; a guard test calls every documented operation anonymously | `test_route_access.py` |
| Privilege escalation inside an organisation | Role checks (member/admin/owner) on admin operations, tested per route | `require_role`, scoring/demo/companies tests |
| Password guessing | Argon2id, per-email and per-IP login throttling, per-IP rate limits | ADR-0003, ADR-0013 |
| Account enumeration via login | Identical timing for unknown emails (cached dummy hash, measured equal: 57 ms vs 57 ms) and identical errors | `burn_password_check`, regression test |
| Session theft / fixation | Random 256-bit tokens stored hashed; new token at login; `__Host-` cookie, Secure, HttpOnly, SameSite=Lax; idle and absolute expiry; server-side revocation at logout | ADR-0003 |
| CSRF | SameSite=Lax plus Origin check on state-changing requests | `OriginCheckMiddleware` |
| XSS | React escapes all output; no raw HTML anywhere (checked); strict CSP without inline scripts; AI and website text rendered as text (tested with HTML payloads) | Caddyfile, component tests |
| SQL injection | SQLAlchemy parameters everywhere; no SQL built from strings outside migrations (checked) | — |
| SSRF via enrichment | Public-address-only network backend (checked at connect time, incl. redirects and DNS rebinding), robots.txt, size/time limits, no proxy env | ADR-0009 |
| Prompt injection / AI hallucination | Website text passed as escaped data, no tools, schema-constrained output, every claim's quote verified against the source | ADR-0010, ADR-0012, eval injection cases |
| Running up AI costs | AI off for public signups, per-org daily caps, global monthly budget checked by API and worker | ADR-0013 |
| Denial of service | Body size limit, rate limits, pagination caps, CSV size/row limits, job queue for slow work | ADR-0013 |
| Leaking data to monitoring | Sentry receives no bodies, cookies, query strings, prompts or frame variables (enforced twice; verified) | ADR-0014 |
| Secrets exposure | Secrets only in git-ignored env files / GitHub environment secrets; SecretStr in code; gitleaks over the full history in CI; production refuses weak passwords | CI, `config.py` |
| Supply chain | Locked dependencies with hashes; releases at least 14 days old; images pinned by digest; Actions pinned by commit; pip-audit and npm audit in CI | CI, ADR-0002 |
| Server compromise | Non-root, read-only containers without capabilities; only Caddy exposed; SSH keys only, no root login; firewall; automatic security updates; backups encrypted to an offline key | `deploy/` |
| Data loss | Nightly encrypted backups, restore drill with checks | `docs/operations.md` §6 |

## 4. Phase 8 review (2026-11-05)

| Check | Result |
|---|---|
| `pip-audit` (all locked Python packages, hashes required) | No known vulnerabilities |
| `npm audit --omit=dev` (shipped frontend code) | 0 vulnerabilities |
| `npm audit` incl. dev tools | 10 moderate, one root cause (see accepted risks) |
| Code search: SQL from strings, raw HTML, request models without `extra="forbid"` | None found |
| Anonymous access to every documented API operation | All refuse with 401 except the 5 public ones; sabotage test confirmed the check works |
| Login timing, unknown vs known email | Equal (57 ms / 57 ms); regression test added |
| OWASP ZAP baseline (with AJAX spider) against the production build | 0 failures, 63 passed, 5 warnings, all triaged below |
| Production stack in a browser | No CSP violations; `__Host-` Secure HttpOnly SameSite=Lax cookie |

ZAP warnings: cacheable static assets and Cache-Control (intended: hashed assets are immutable,
HTML is `no-cache`); CSP allows inline styles (accepted, below); "modern web application"
(informational); Cross-Origin-Embedder-Policy missing (only needed for cross-origin isolation,
which the app doesn't use; `Cross-Origin-Resource-Policy: same-origin` was added instead).

Re-run the scan against a local production stack:

```bash
docker compose -f deploy/compose.prod.yaml up -d --build --wait
docker run --rm --network container:sia-prod-web-1 -v "$PWD/zap:/zap/wrk:rw" \
  zaproxy/zap-stable:20261016 zap-baseline.py -t https://localhost/ -j -I -r report.html
```

## 5. Accepted risks

| Risk | Why accepted | Revisit |
|---|---|---|
| `minimatch` DoS advisory (GHSA-g3hv-75wg-m249) in ESLint tooling | Dev-only, needs attacker-controlled glob patterns; the fix (11.0.1) is younger than our 14-day rule | On or after 2026-11-10: add an npm override to `minimatch >= 11.0.1` |
| CSP `style-src 'unsafe-inline'` | UI components position overlays with style attributes; inline scripts stay forbidden, which is what blocks XSS | If the UI library supports nonces |
| Signup reveals that an email is already registered | Clear UX; signups are limited to 5 per hour per IP | When email verification is added |
| No email verification or password reset | Features not built yet (no email delivery) | Before inviting real customers |
| `deploy` user is in the `docker` group (effectively root) | Single-purpose server; key-only login; no password | If the server hosts anything else |
| All members of an organisation see all its data | Product decision: teams share accounts | If per-record permissions are requested |
| ICP preview costs ~2 s of database time at 50k companies | Admin-only and rate limited | If tenants grow far beyond 50k (ADR-0011) |
| Users behind one shared IP share rate limits | Limits are generous for that reason | If customers report 429s |
