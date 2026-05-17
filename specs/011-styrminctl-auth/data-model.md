# Data Model: `styrminctl` Authentication

## Domain entities (unchanged)

This feature does not change the backend domain model. For completeness:

- **Session** *(backend, owned by ADR-024)* — server-side row keyed by an opaque token; lifetime governed by the backend. The CLI does not observe Session rows directly; it only holds tokens.
- **Session token** *(SDK / backend)* — opaque string returned by the `login` mutation, carried by the SDK as `Authorization: Bearer <token>`. Treated as opaque on the client; no parsing.

## CLI-local data

### Token store file

**Path**: `${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/token`

**File mode**: `0600`. **Parent directory mode**: `0700`. The CLI MUST reassert these permissions on every save (chmod after open) and refuse to write if the reassert fails.

**Format**: JSON object on a single root.

```json
{
  "schema_version": 1,
  "tokens": {
    "<canonical_server_url>": "<opaque session token>"
  }
}
```

Fields:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `schema_version` | integer | yes | `1` for this feature. Future profile-aware shape bumps to `2`. Unknown values → `TokenStoreError`. |
| `tokens` | object | yes | Map of canonical server URL → opaque token string. May be empty (`{}`) — represents "logged out of all servers". |

**Canonical server URL** (the key shape):

- Lowercase scheme and host.
- Preserve port verbatim (default ports are NOT normalised).
- Strip trailing slash from path.
- Implementation in `cli/src/styrminctl/auth/token_store.py::canonicalise()`.

Examples:

| Input `STYRMIN_ADDRESS` | Canonical key |
|---|---|
| `http://prod:8000` | `http://prod:8000` |
| `http://Prod:8000/` | `http://prod:8000` |
| `HTTPS://Styrmin.Example.com/` | `https://styrmin.example.com` |
| `http://prod:8001` | `http://prod:8001` (distinct from `:8000`) |

### Lifecycle

| Operation | Effect on file |
|---|---|
| `login` | Resolves canonical key from `STYRMIN_ADDRESS`. Creates parent dir (mode `0700`) if missing. Reads current store. Sets `tokens[<key>] = <new token>`. **Writes atomically**: serialise JSON → write to `<target>.tmp.<pid>.<random>` with mode `0600` → `os.rename()` over the target. `os.rename()` is atomic on POSIX, so a concurrent reader sees either the old or the new file but never a partial one, and a concurrent save against a *different* canonical key is guarded by re-reading inside the same load-then-rename cycle (see E2 in critique 2026-05-17). |
| `logout` | Calls backend `logout` (best-effort). Deletes `tokens[<key>]` if present. If `tokens` becomes empty, the file is rewritten with `tokens: {}` (file is NOT removed — easier `whoami`/`login` UX next time). |
| `whoami` / authenticated command | Read-only. Reads `tokens[<key>]`. Never mutates. |
| Token rejected as stale | Read-only. The CLI does NOT auto-delete the entry — the user can inspect and `rm` manually. |

### Invariants

- `schema_version == 1` for everything this feature ships. A future contributor may add `2`; until then, any other value is a `TokenStoreError`.
- File mode is `0600` after every successful save. Parent directory mode is `0700` after every successful save.
- **Save is atomic** via temp-file + `os.rename()`. A reader at any point sees either the prior valid state or the new valid state, never an interleaved or truncated file. The temp filename includes pid + random suffix so two concurrent saves do not race on the temp file itself.
- Empty string is NEVER a valid token value. An entry whose value is `""` is treated as absent (so an accidental empty assignment never masquerades as authenticated).
- The file is human-readable JSON on purpose; we accept the trade-off of "user could `cat` and copy the token" because the file is `0600` anyway, and the alternative (binary / encrypted blob) needs a key-management story that v1 explicitly defers.

## CLI-local types

These are not domain entities; they live entirely within `cli/`.

### `TokenSource` (literal / enum)

Values:

- `"env"` — token came from `STYRMIN_TOKEN`.
- `"file"` — token came from the token store on disk.
- `"auto-login"` — token came from an in-process `STYRMIN_USERNAME`+`STYRMIN_PASSWORD` round-trip.
- `"none"` — no token (only `login` and `--help` work).

Used by `CredentialResolver.resolve()` and consumed by `whoami` to render the `Authenticated via: …` line.

### `TokenStoreError` (CLI-only Exception)

Raised by `TokenStore` for:

- Corrupt JSON (could not parse).
- Unknown `schema_version`.
- Parent directory not writable.
- chmod failure on file or directory.

Each instance carries a human message naming the file path. Rendered by the top-level CLI error boundary as a single-line `sys.exit(<msg>)`.

### `AsymmetricEnvCredentialsError` (CLI-only Exception)

Raised by `CredentialResolver` when exactly one of `STYRMIN_USERNAME` / `STYRMIN_PASSWORD` is set. Carries the missing-variable name. Rendered as a single line by the CLI error boundary.

## What is NOT modelled here

- Password material — never persisted, never instantiated as a typed object that outlives the function call. A plain `str` flows from `getpass` → `client.auth.login(username, password)` and is then dropped.
- Backend `Session` lifecycle (creation, expiry, revocation). Owned by ADR-024.
- Multi-profile shape (`tokens.<url>.<profile>`). Reserved for `schema_version: 2`.
