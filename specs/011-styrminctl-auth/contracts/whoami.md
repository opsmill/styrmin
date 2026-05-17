# Contract: `styrminctl whoami`

## Synopsis

```
styrminctl whoami
```

No arguments.

## Inputs

- `STYRMIN_ADDRESS` (env) — required.
- Whatever credentials are visible per the four-rung precedence ladder (`STYRMIN_TOKEN`, token store, `STYRMIN_USERNAME`+`STYRMIN_PASSWORD`).

## Behaviour

1. Call `get_client()` which returns `(client, source)` via `CredentialResolver`.
2. If `source == "none"` → exit non-zero with the friendly "Not logged in" message (see Error contract below). Do NOT call any GraphQL.
3. Otherwise call `await client.auth.current_user()`. The SDK returns a `CurrentUserCurrentUser | None`.
4. If the result is `None`, exit non-zero with "Not logged in" (treating null `currentUser` as unauthenticated).
5. Print the identity block on stdout.

## Output (stdout, happy path)

```
Username: alice
Display name: Alice Example
Role: PLATFORM_ENGINEER
Authenticated via: token file (/home/alice/.local/share/styrminctl/token)
```

The exact source-line variants:

| `source` | Stdout line |
|---|---|
| `"env"` | `Authenticated via: env (STYRMIN_TOKEN)` |
| `"file"` | `Authenticated via: token file (<absolute path>)` |
| `"auto-login"` | `Authenticated via: auto-login (STYRMIN_USERNAME)` |

Exit 0.

The token value is NEVER printed.

## Output (stderr / failure)

| Condition | Stderr line | Exit code |
|---|---|---|
| `source == "none"` (no credentials) | `Not logged in. Run \`styrminctl login\` or set STYRMIN_TOKEN.` | non-zero |
| `StyrminAuthenticationError` (stale / revoked token) | `Not logged in. Run \`styrminctl login\` or set STYRMIN_TOKEN.\nRun \`styrminctl login\` to refresh.` | non-zero |
| `currentUser` returns `None` | `Not logged in. Run \`styrminctl login\` or set STYRMIN_TOKEN.` | non-zero |
| `AsymmetricEnvCredentialsError` | `STYRMIN_USERNAME is set but STYRMIN_PASSWORD is not (or vice versa).` | non-zero |
| `TokenStoreError` (corrupt JSON, unknown schema_version) | `Token store at <path> is unreadable: <message>.` | non-zero |
| Network failure | `Could not reach <STYRMIN_ADDRESS>: <error class>.` | non-zero |

All failures: single line on stderr, no Python traceback.

## Side effects

None. Pure read.

## Why source-attribution belongs in `whoami`

Most "wrong user" bugs at the CLI level are credential-resolution bugs: the user thinks they are using their on-disk token but actually have a stale `STYRMIN_TOKEN` exported in a parent shell. The source line resolves this in one shot. Cost: one extra line. Risk: tells an attacker which env var the user uses, but they would learn that from any documented CLI surface; the cost is negligible.
