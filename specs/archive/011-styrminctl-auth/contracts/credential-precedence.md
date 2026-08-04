# Contract: Credential Precedence Ladder

This is the contract that `CredentialResolver.resolve(settings, env, token_store)` MUST satisfy.

## Inputs

- `settings.server_address` — already normalised (trailing slash stripped) by `Settings`. Canonicalised again here by `TokenStore.canonicalise()` (idempotent).
- `env` — process environment (or a `dict[str, str]` stub in tests).
  - `STYRMIN_TOKEN` — opaque token string; empty string treated as unset.
  - `STYRMIN_USERNAME` — username for auto-login.
  - `STYRMIN_PASSWORD` — password for auto-login.
- `token_store` — a `TokenStore` instance (real or stubbed).

## Output

`(token: str | None, source: TokenSource)` where `TokenSource ∈ {"env", "file", "auto-login", "none"}`.

If `source == "auto-login"`, the resolver MUST also have performed an in-process `client.auth.login(username, password)` call against `settings.server_address`; the returned `token` is the result. **This is the only rung that performs a network round-trip during resolution.**

## Decision table (highest rung wins)

| Rung | Condition | Action | Returns |
|---|---|---|---|
| 1 | `STYRMIN_TOKEN` is set and non-empty | use it directly | `(token, "env")` |
| 2 | rung 1 false; `token_store.get(canonical_url)` returns a non-empty string | use it directly | `(token, "file")` |
| 3 | rungs 1 & 2 false; `STYRMIN_USERNAME` AND `STYRMIN_PASSWORD` both set and non-empty | call `auth.login` in-process; do NOT persist | `(token, "auto-login")` |
| 4 | exactly one of `STYRMIN_USERNAME` / `STYRMIN_PASSWORD` is set and non-empty | raise `AsymmetricEnvCredentialsError` | — |
| 5 | none of the above | (no token) | `(None, "none")` |

Note: rung 4 is a hard error, not a fall-through. A pipeline that exports only one of the two variables is misconfigured and the CLI MUST fail fast rather than silently fall back to unauthenticated.

## Test matrix (mandatory)

| # | `STYRMIN_TOKEN` | Disk token | `STYRMIN_USERNAME` | `STYRMIN_PASSWORD` | Expected `source` | Persists? |
|---|---|---|---|---|---|---|
| 1 | "tok-env" | — | — | — | `env` | no |
| 2 | "" | "tok-disk" | — | — | `file` | no |
| 3 | unset | "tok-disk" | — | — | `file` | no |
| 4 | unset | — | "alice" | "secret" | `auto-login` | no |
| 5 | unset | "tok-disk" | "alice" | "secret" | `auto-login` | no — env-var wins over disk |
| 6 | "tok-env" | "tok-disk" | "alice" | "secret" | `env` | no |
| 7 | unset | — | "alice" | — | RAISES `AsymmetricEnvCredentialsError` | — |
| 8 | unset | — | — | "secret" | RAISES `AsymmetricEnvCredentialsError` | — |
| 9 | unset | — | — | — | `none` | no |

These are the cases `cli/tests/auth/test_resolver.py` MUST cover.

## Invariants

- The resolver does NOT mutate the token store. Persistence is exclusively the responsibility of `login`.
- The resolver MAY perform exactly one network call (rung 3); it never retries or caches across invocations.
- The "auto-login" rung returns the freshly-acquired token in-process. The CLI uses it for the current invocation only. The caller (commands / `get_client`) MUST NOT persist it.
- "Empty string" is treated as "unset" for `STYRMIN_TOKEN`, `STYRMIN_USERNAME`, and `STYRMIN_PASSWORD`. This guards against CI templates that produce empty values when a secret is missing.

## Failure surface (raised, not returned)

- `AsymmetricEnvCredentialsError` — rung 4 above.
- `StyrminAuthenticationError` — propagated unchanged from rung 3's `auth.login` call when the backend rejects the env-var credentials.
- `TokenStoreError` — propagated from rung 2's `token_store.get()`.

All three are handled by the CLI's top-level error boundary (`cli/src/styrminctl/errors.py`) and rendered as single-line stderr messages.
