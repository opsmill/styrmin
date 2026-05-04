# ADR-024: Authentication via opaque server-side session tokens with dual transport

**Status**: Accepted
**Date**: 2026-05-04
**Source**: GitHub issue [#179](https://github.com/opsmill/styrmin/issues/179) + [#184](https://github.com/opsmill/styrmin/issues/184)

## Context

Styrmin currently has no concept of identity. Anyone with network access to the backend can run any GraphQL operation against any cluster — there is no `User` model, no session handling, no authentication middleware, and no authorization checks on resolvers. This blocks every multi-operator deployment scenario, attribution requirement, and downstream multi-tenancy or audit work.

The auth foundation issue requires a single, well-defined credential mechanism that:

1. Works for both browser-based clients (the React frontend) and server-side scripts (the Python SDK and CI pipelines), without forcing each to learn the other's transport quirks.
2. Can be revoked instantly on logout or when an admin deactivates a user — no dangling token can outlive the decision to revoke.
3. Survives a database snapshot leak: the DB must not contain anything that can be replayed as a credential.
4. Survives a process restart (no in-memory-only sessions) and tolerates concurrent backend replicas without cross-replica cache coordination.
5. Has a defined absolute lifetime and a defined idle lifetime, with sliding refresh that does not turn the auth path into a hot-write contention point.
6. Stores password material under the OWASP-recommended hashing tuple at the time of writing, with a path to bump parameters without a synchronous migration.

The design space splits along two well-known axes: stateful opaque tokens vs. stateless signed tokens (JWT), and bearer-header vs. cookie transport. Picking one of each in isolation produces a usable system; picking both transports backed by a single server-side row gives the best fit for our two distinct caller populations without doubling the auth surface.

## Decision

### Sessions are server-side and opaque

A login mutation creates a `session` row keyed to the user. The token is `secrets.token_urlsafe(32)` (32 bytes of entropy → ~43 URL-safe base64 chars). The DB stores `sha256(token)` (`bytea`, unique-indexed); the auth path hashes the incoming token and looks up by hash. The raw token is returned to the caller exactly once at login and never recoverable from the DB.

**No JWT.** Stateless signed tokens cannot be invalidated on logout or deactivation without a server-side revocation list, which negates their stateless property. Instant revocation is a hard requirement (deactivating a teammate must terminate their access on the next request, not on the next token expiry); a session row gives that for free.

**SHA-256, not argon2, on the token hash.** Argon2 protects guessable inputs. A 256-bit-entropy session token is not guessable in any meaningful sense, and per-request argon2 verification would add tens of milliseconds to every authenticated call. SHA-256 is the correct primitive: fast, indexable, and irreversible against the realistic threat (a stolen DB snapshot).

### Dual transport, one session row

Each session is reachable through either transport:

- **Browser**: `Set-Cookie: styrmin_session=<token>; HttpOnly; Secure; SameSite=Lax; Path=/` on the login response. The frontend never touches the token in JavaScript — a successful XSS cannot exfiltrate it.
- **SDK / scripts**: `Authorization: Bearer <token>`. The SDK never touches a cookie jar.

The auth middleware accepts either, prefers the bearer header when both are present (so an SDK call from a browser-loaded notebook is unambiguous), and resolves to the same session row.

Both transports back the same row. Logout invalidates the row, which invalidates the token regardless of how it was being carried. There is no separate "browser session" and "SDK session" abstraction.

### Lifetime: 30 days absolute, 7 days idle, with sliding refresh

Two expiry checks gate every authenticated request:

- `now < session.created_at + 30 days` (absolute cap; non-extendable).
- `now < session.last_used_at + 7 days` (idle cap; advanced by sliding refresh).

On a successful auth, the path advances `last_used_at` to `now()`, but **debounced**: the write is skipped if `now - last_used_at < 60s`. Without the debounce, every authenticated request becomes a UPDATE on a single row, producing hot-row contention on busy users. 60 seconds is a deliberate floor — tight enough that the idle window stays meaningful, loose enough that a request burst is one write, not one-per-request.

Lazy invalidation in the auth path is the source of truth: an expired session is deleted on the next attempt to use it. A daily Prefect cleanup task is belt-and-suspenders for never-touched-again rows so the table cannot grow unboundedly.

Concurrent sessions per user are uncapped. Logout invalidates only the calling session (one cookie / one bearer call ⇒ one revocation), not all of the user's sessions. `changePassword` invalidates all *other* sessions and preserves the calling one, so a user rotating credentials does not log themselves out of the device they're currently on but does kick off any other device whose token might already be compromised.

### No CSRF token in v1

The standard mitigation for cookie-borne credentials is a CSRF token (synchronizer token, double-submit, etc.). We deliberately omit it and rely on three converging properties:

1. **`SameSite=Lax`** on the session cookie. A cross-site `POST` does not carry the cookie. `Lax` (vs. `Strict`) preserves the top-level GET navigation case (a user clicking a link to Styrmin from elsewhere stays logged in), which is what we want for usability.
2. **POST-only mutations.** The GraphQL endpoint accepts mutations only over POST. There is no `GET /mutate?...` surface to be tricked into following.
3. **Bearer immunity.** The SDK does not use cookies, so SDK callers are wholly outside the CSRF threat model. Only browser sessions are exposed at all, and `SameSite=Lax` already covers the realistic browser cases.

A CSRF token would be a fourth, redundant layer for an attack class the first three already block. Adding it later if our threat model changes (e.g., we expose a non-`Lax` cookie path or accept `application/x-www-form-urlencoded` mutations) is a strictly additive change.

### Password handling

argon2id via `argon2-cffi` with `memory_cost=19456 KiB, time_cost=2, parallelism=1` — the OWASP 2024 conservative tuple. `argon2.PasswordHasher.check_needs_rehash()` runs on every successful login: when the global parameter tuple is bumped, the next login of each user automatically rehashes that user's password under the new parameters. No synchronous migration step is ever required to roll out a parameter bump.

Policy:

- Minimum 12 characters, no composition rules (per NIST SP 800-63B — composition rules degrade entropy in practice).
- Maximum 256 characters (defends against argon2-as-DoS via gigantic inputs).
- No breach-corpus check in v1; can be added as a strictly additive validator later.
- No brute-force / lockout protection in v1 — accepted risk, revisited if abuse is observed.

`passwordHash` is **never** present in the GraphQL schema. The loguru serializer redacts `passwordHash`, session tokens (raw or sha256 form), and any field whose name appears in the password-input list. Logging credentials is a forbidden operation enforced at the serializer layer, not at each call site.

### Bootstrap

Default-admin seeding runs in the FastAPI lifespan hook (`app_initialization()`), **not** in an Alembic migration. Alembic migrations stay pure DDL — running data migrations through Alembic crosses a layer boundary we keep clean elsewhere in the codebase.

The hook reads `STYRMIN_ADMIN_USERNAME` (default `admin`) and `STYRMIN_ADMIN_PASSWORD`. If the password env var is unset, the hook generates a random one and logs it once at WARN level. The hook is multi-replica-safe via `INSERT ... ON CONFLICT (username) DO NOTHING RETURNING id` — only the replica that wins the insert race logs the generated password; losing replicas observe a no-op and log nothing. SQLite ≥ 3.24 is required for `ON CONFLICT` support and is documented as a runtime prerequisite.

If any user already exists, the hook is a no-op even if the env vars are set. Re-deploying never resets an admin account.

### Generic login error

`login` with a wrong password, a nonexistent username, or a deactivated user all return the same `INVALID_CREDENTIALS` structured error. The error message does not leak which axis failed. This costs us a sliver of debuggability but closes the username-enumeration channel.

## Consequences

- **Easier**: instant revocation works the way operators expect — `logout`, `deactivateUser`, and admin-driven session deletion all take effect on the next request, not at some indeterminate future expiry.
- **Easier**: a database snapshot leak yields no usable credentials. Tokens are unrecoverable hashes; passwords are argon2id at conservative parameters.
- **Easier**: one session abstraction serves both transports, so "what is the session lifetime?" / "how does logout work?" / "where is the token revoked?" have a single answer regardless of caller.
- **Easier**: parameter bumps for argon2id roll out automatically through `check_needs_rehash` on next login; no migration choreography ever required.
- **Easier**: bootstrap is operator-friendly out of the box — a fresh Helm install with no `STYRMIN_ADMIN_PASSWORD` env var is still usable, because the generated password lands in the operator's logs.
- **Harder**: every authenticated request issues at least one DB read (session lookup by token hash) and may issue one debounced write (`last_used_at`). For an unloaded backend this is invisible; under sustained load it is the auth path's dominant cost. Mitigated by the 60s debounce, the unique-indexed `token_hash` lookup, and the lazy-invalidation path that deletes expired rows as it finds them. Stateless JWT would avoid the read but cannot meet the revocation requirement.
- **Harder**: the `session` table grows with concurrent sessions per user. Mitigated by lazy invalidation, the daily Prefect cleanup task, and the absolute 30-day cap that bounds the worst case.
- **Harder**: omitting the CSRF token is a deliberate threat-model assumption that depends on `SameSite=Lax` and POST-only mutations remaining true. A future change that introduces a non-`Lax` cookie path or a GET-mutation shortcut would silently re-open the gap. Documented here so the constraint is auditable and the next contributor sees the rationale before changing those defaults.
- **Harder**: bootstrap-generated admin passwords appear in stdout logs once. An operator who lost the line cannot recover the password and must reset it via SDK or DB — accepted on the basis that operators running fresh installs will tail the boot logs once and capture the line.
- **Convention to replicate**: any future credential-bearing field uses `sha256(value)` storage with a unique index for lookup, and any future password-bearing field uses argon2id with `check_needs_rehash` on verification. Any new sensitive field name must be added to the loguru redaction list at the serializer layer.

## Alternatives Considered

- **JWT (signed stateless tokens)**: Rejected. Solves no problem we have (we already need a DB row for the user record) and breaks instant revocation. A blocklist would re-add the DB read this design supposedly avoided.
- **Bearer-only, no cookie**: Forces the frontend to store the token in `localStorage` or memory. `localStorage` is XSS-exfiltratable (the whole point of `HttpOnly` is that it isn't); in-memory is hostile to refreshes and multi-tab use. Cookie + bearer covers both populations cleanly.
- **Cookie-only, no bearer**: Forces the SDK to handle a cookie jar and bookkeep `Set-Cookie` headers across requests. Adds machinery for no benefit when a single header already does the job.
- **Two separate session models (browser-session vs. api-token)**: Doubles the data model, doubles the lifetime/expiry logic, doubles the revocation surface. Rejected — operators will end up needing both anyway, and one shared abstraction is dramatically simpler.
- **Per-request hot `last_used_at` write (no debounce)**: Rejected. Single-row write contention for any user with sustained traffic; provides no observable user-facing benefit over a 60s debounce.
- **bcrypt or scrypt for passwords**: Rejected in favour of argon2id, which is the OWASP 2024 first recommendation and has a memory-hard resistance profile bcrypt does not.
- **Argon2 on session token verification**: Rejected. Argon2 is calibrated for guessable inputs; on a 256-bit-entropy random token it adds latency without raising the security floor.
- **CSRF synchronizer token in v1**: Reconsidered and deferred. The realistic CSRF surface is closed by `SameSite=Lax` + POST-only mutations + bearer-only SDK; the token would be a fourth redundant layer. A future change that weakens any of those preconditions can add the token without disturbing the rest of the design.
- **Brute-force lockout on login**: Out of scope for v1. A naive lockout becomes a DoS amplifier for a known username; doing it correctly (per-IP + per-user backoff with monitoring) is more work than v1 needs and can be added without schema changes.
- **Disk-persisted SDK tokens**: Rejected. Tokens on disk become a credential-management problem for the caller's secret store. The SDK accepts a token from the constructor or `STYRMIN_TOKEN`; persistence (if needed) belongs in the caller's secret manager, not the SDK.
