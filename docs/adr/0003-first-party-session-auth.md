# ADR-0003: First-party session authentication

- **Status:** Accepted
- **Date:** 2026-11-04

## Context

The product needs user login plus organisations, memberships and roles. Options: a managed
identity provider (Clerk, Auth0, WorkOS), stateless JWTs, or server-side sessions.

## Decision

Implement first-party authentication:

- Passwords hashed with **Argon2id** (`argon2-cffi`).
- Opaque random session tokens in **HTTP-only, Secure, SameSite** cookies; only a hash of the
  token is stored in PostgreSQL.
- CSRF protection for state-changing requests.
- Organisations, memberships and roles are our own tables regardless of identity provider.

## Consequences

- No third-party account or vendor dependency; sessions can be revoked instantly (unlike JWTs).
- We own security-sensitive code, so it requires careful tests (login throttling, session
  expiry/rotation, enumeration-safe errors).
- SSO (OIDC/SAML) can be added later as an additional login method without changing the
  tenancy model.
