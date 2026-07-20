# ADR-0011: Keycloak Registration and Account Projection

- Status: Accepted for implementation
- Date: 2026-07-20
- Owners: Identity platform

## Context

CyberControl needs email and phone registration without introducing a second
password authority or weakening the existing OIDC tenant boundary. Keycloak
is an external system, so a PostgreSQL transaction cannot atomically include a
Keycloak Admin API call.

## Decisions

1. Keycloak is the only authority for passwords, password hashes, OIDC
   subjects, and realm roles. The application database never stores a password,
   password hash, verification code, Keycloak access token, or administrative
   token.
2. Migration `20260720_0010` adds an application-side account projection,
   registration state snapshots, verification challenges/rate-limit state,
   consent evidence, and reconciliation jobs. Revisions `0001` through `0009`
   are immutable.
3. Every new table is tenant scoped, uses `FORCE ROW LEVEL SECURITY`, and is
   granted only to the restricted runtime role. Registration tenant identity is
   derived from a server-verified signed invitation. Development may use the
   server-configured `demo-academy` fallback; the fallback is rejected in
   production.
4. Registration is a state machine. A SERIALIZABLE PostgreSQL transaction
   reserves idempotency and records `KEYCLOAK_PENDING`; the Keycloak call is
   then performed with bounded timeouts; a second SERIALIZABLE transaction
   creates the projection, consumes the challenge, appends audit and Outbox
   evidence, and records `COMPLETED`. Failed external work creates a durable
   reconciliation job or is compensated by deleting the newly created user.
5. Contact values are normalized before use, encrypted at rest with a
   deployment-provided key, and indexed only by a keyed SHA-256 lookup digest.
   Verification codes are generated in memory and only their keyed digest is
   persisted. The local fixture inbox is loopback-only and disabled in
   production.
6. New accounts receive only the learner role. Reviewer and tenant
   administration permissions are never accepted from the client and must be
   assigned by server policy or an authorized administrator.
7. Account profile writes, contact changes, status changes, registration
   transitions, challenge events, and consent are auditable. Append-only
   evidence is protected by database triggers; Outbox messages are inserted in
   the same transaction as the corresponding state change.
8. Before an authenticated profile, contact, or account-status write reaches
   Keycloak, PostgreSQL persists an encrypted snapshot of the prior Keycloak
   representation in a tenant-scoped reconciliation job. A partial unique
   index permits only one active external mutation per account. The projection
   commit completes that job atomically; a timeout, process crash, or database
   failure leaves the job runnable so the reconciler restores the prior
   identity-provider state and releases the idempotency lease. Exhausted
   compensation marks the account `RECONCILIATION_REQUIRED` and emits audit and
   Outbox evidence for operator intervention.
9. Reconciliation tenant discovery uses a dedicated PostgreSQL login that is
   `NOSUPERUSER` and `NOBYPASSRLS`. A narrowly scoped RLS policy and column grant
   allow that login to read only distinct `tenant_id` values from the
   reconciliation catalog; it cannot read job documents, account projections,
   contact data, audit records, or other tenant tables. Tenant-specific work is
   then claimed through the normal `liyans_app` connection with a populated
   `TenantContext`.
10. A reconciliation claim is a renewable lease, not permanent ownership.
    `RUNNING` jobs whose `updated_at` predates the configured claim lease are
    reclaimed after process restart. A stale claim with remaining attempts is
    retried idempotently; an already exhausted stale claim fails closed and
    moves the affected account to `RECONCILIATION_REQUIRED`. Each claim receives
    a new random claim token and records the worker instance. The finishing
    SERIALIZABLE transaction uses that token as a compare-and-set guard, so a
    delayed worker whose lease was reclaimed cannot append duplicate audit or
    Outbox evidence.

## Consequences

- A successful Keycloak call can temporarily precede the projection commit;
  reconciliation is therefore a first-class runtime capability, not an
  implicit best effort.
- Existing OIDC login and Topic1-Topic4 contracts remain unchanged. Identity
  contracts are versioned separately and are consumed by the later frontend
  branch.
- Production deployments must provide the identity encryption secret, lookup
  pepper, verification-code pepper, and signed-invitation secret through an
  external secret mechanism. They must also configure the dedicated
  reconciliation-catalog database URL; the production process refuses to start
  the identity runtime without it.
