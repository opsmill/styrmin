# Contract: `styrminctl login`

## Synopsis

```
styrminctl login [--username U]
```

## Arguments

| Name | Required | Source | Notes |
|---|---|---|---|
| `--username` / `-u` | no | flag | When omitted, the CLI prompts on stdin (visible). |
| password | yes | hidden prompt via `getpass.getpass("Password: ")` | Never passed as a flag. Never read from any env var by `login` itself (the env-var path is auto-login, FR-005). |

## Inputs

- `STYRMIN_ADDRESS` (env) — required; resolves through `Settings` exactly as today.
- No other env var is consulted by `login` directly. `login` is the one command that intentionally *bypasses* the precedence ladder of `get_client()` because its job is to *produce* a token, not consume one.

## Behaviour

1. Read `STYRMIN_ADDRESS`. Construct an unauthenticated `StyrminClient`.
2. Prompt for `username` (visible) if not provided as a flag.
3. Prompt for `password` (hidden) via `getpass`.
4. Print `Authenticating against <STYRMIN_ADDRESS> …` BEFORE the round-trip, so the user can abort if the address is wrong. (Satisfies FR-012.)
5. Call `await client.auth.login(username, password)`. This returns a `LoginLogin` containing `token` and `user`.
6. Compute canonical URL from `STYRMIN_ADDRESS`.
7. Persist `token` to the token store under that canonical URL via `TokenStore.set(...)`. The store creates the parent directory (mode `0700`) if missing and **writes the file atomically** (temp-file + `os.rename()`), with the resulting file at mode `0600`. Concurrent `login`s against different canonical URLs never lose entries.
8. Print `Logged in to <STYRMIN_ADDRESS> as <username>` on stdout. Exit 0.

## Output (stdout)

Happy path (multi-line):

```
Authenticating against http://prod:8000 …
Logged in to http://prod:8000 as alice
```

## Output (stderr / failure)

| Condition | Stderr line | Exit code |
|---|---|---|
| Invalid credentials (`StyrminAuthenticationError` with code `INVALID_CREDENTIALS`) | `Login failed: invalid username or password.` | non-zero |
| Network failure | `Login failed: could not reach <STYRMIN_ADDRESS> (<error class>).` | non-zero |
| `TokenStoreError` after successful backend login (chmod failure, etc.) | `Logged in to <address> as <username>, but could not save token: <message>.` | non-zero |
| `getpass` EOF on non-TTY stdin | `Cannot prompt for password: stdin is not a terminal. Use STYRMIN_USERNAME + STYRMIN_PASSWORD for non-interactive auth.` | non-zero |

In every failure case: single line on stderr, no Python traceback.

## Side effects

- Writes / updates one entry in the token store. Other server entries are untouched.
- Does NOT call `auth.logout()` for any prior token under the same key — overwriting is sufficient and the prior session expires server-side when this one supersedes it.

## Idempotency

Re-running `login` overwrites the entry for the same canonical URL with a fresh token. No accumulation.

## Out of scope

- `--token <value>` flag (env var only for v1).
- Storing a refresh token or expiry (backend does not surface one — see research R1).
