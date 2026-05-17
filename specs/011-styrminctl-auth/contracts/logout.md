# Contract: `styrminctl logout`

## Synopsis

```
styrminctl logout
```

No arguments.

## Inputs

- `STYRMIN_ADDRESS` (env) — used to compute the canonical key whose entry will be deleted.

## Behaviour

1. Resolve canonical URL from `STYRMIN_ADDRESS`.
2. Look up `token = TokenStore.get(canonical_url)`. If absent: skip backend call.
3. If a token was found, construct an authenticated `StyrminClient` with `token=token` and call `await client.auth.logout()`. **Errors here are swallowed** — network failure, `UNAUTHENTICATED`, or any GraphQL error is captured and ignored. The local delete proceeds regardless.
4. `TokenStore.delete(canonical_url)` — removes the entry. If the file becomes empty, the file is rewritten with `tokens: {}` (not removed).
5. Print `Logged out of <STYRMIN_ADDRESS>` on stdout. Exit 0.

## Output (stdout)

Happy path:

```
Logged out of http://prod:8000
```

Idempotent re-run (no prior token):

```
Logged out of http://prod:8000
```

(Same wording; succeeds silently. See FR-002 and FR-010.)

## Output (stderr / failure)

| Condition | Stderr line | Exit code |
|---|---|---|
| `TokenStoreError` on delete (corrupt file, chmod failure) | `Could not update token store: <message>.` | non-zero |
| Disk write failure on the rewritten store | same as above | non-zero |

Backend errors during `auth.logout()` are NEVER surfaced to the user.

## Side effects

- Removes one entry from the token store. Other server entries untouched.
- Best-effort: ends the server-side session if reachable; harmless no-op otherwise.

## Idempotency

Running `logout` twice in a row succeeds both times. The second run is a no-op as far as the local file is concerned and does not attempt a backend round-trip (there is no token to send).

## Why not delete the file entirely

`whoami` and `login` are easier to reason about when the file always exists in a valid state. Always-present + always-valid JSON beats "file may or may not exist" branches in every call site.
