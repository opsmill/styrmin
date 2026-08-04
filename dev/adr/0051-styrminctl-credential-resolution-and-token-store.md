# ADR-051: `styrminctl` credential resolution ladder and versioned token store

**Status**: Accepted
**Date**: 2026-08-04
**Source**: specs/archive/011-styrminctl-auth/research.md (R2, R4, R6, R8, R10, R11), data-model.md
**Related**: [ADR-016](0016-authentication-and-sessions.md) (the server-side sessions
these tokens address), [ADR-047](0047-styrminctl-anonymous-fire-and-forget-telemetry.md)
(the telemetry store reuses this file-writing contract verbatim).

## Context

The `#179` auth foundation gave the backend opaque session tokens and the SDK a
`token=` constructor argument, but `styrminctl` had no way to obtain or keep one:
every invocation needed `STYRMIN_TOKEN` exported by hand. `login` / `logout` /
`whoami` needed somewhere to put a token, and a rule for which credential wins
when several are available at once.

Three constraints shaped the design. The CLI is used interactively *and* in CI,
so an interactive login and a fully non-interactive path both have to work. A
token on disk is a credential, so the file's permissions and its write semantics
are security-relevant. And the SDK reads `STYRMIN_TOKEN` itself, so the CLI has
to be explicit about who resolves credentials or the two layers will disagree
silently.

## Decision

### 1. One resolution chokepoint, four outcomes

All credential resolution happens in `cli/src/styrminctl/client.py::get_client()`
— the single place every command module already obtains a client. Commands are
unaware of where the token came from.

`CredentialResolver.resolve(settings, env, token_store) -> (token, TokenSource)`
evaluates, in this **effective precedence order**:

| Precedence | Source | `TokenSource` |
|---|---|---|
| 1 | non-empty `STYRMIN_TOKEN` | `"env"` |
| 2 | `STYRMIN_USERNAME` + `STYRMIN_PASSWORD` (one in-process login, token **not** persisted) | `"auto-login"` |
| 3 | token-store entry for the canonical server URL | `"file"` |
| 4 | nothing — only `login` and `--help` can succeed | `"none"` |

Exactly one of `STYRMIN_USERNAME` / `STYRMIN_PASSWORD` raises
`AsymmetricEnvCredentialsError` naming the missing variable — it is a hard error,
never a fall-through to the disk token. An **empty** `STYRMIN_TOKEN` counts as
unset, so an accidental `export STYRMIN_TOKEN=` does not mask a valid stored
token.

> Note: the contract document and the resolver's comments number these rungs
> 1/3/2/5 for historical reasons. The numbering is nominal; the table above is
> the order the code evaluates. Explicit env credentials always beat disk.

**The CLI never lets the SDK fall back to reading the environment itself.** When
a token resolves, it is passed explicitly to `StyrminClient(token=...)`. Two
layers independently reading `STYRMIN_TOKEN` is how precedence bugs get shipped.

`get_client()` keeps its original `-> StyrminClient` signature so no existing
command module needed editing. A sibling `get_auth_context() -> AuthContext`
carries the `TokenSource`, and `whoami` is its only consumer. Both delegate to
the same resolver, so behaviour cannot diverge.

**Source attribution is an enum, never a rendered string.** The resolver returns
`TokenSource`; `commands/auth.py::whoami` owns the wording
(`Authenticated via: token file (<path>)`). `token_store.py` knows nothing about
`whoami`, and the SDK has no concept of "where the token came from".

### 2. Token store: versioned JSON, canonical-URL keyed, atomically written

Path `${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/token`, mode `0600`, parent
`0700`, both reasserted on every save — a save that cannot reassert them fails
rather than proceeding.

```json
{ "schema_version": 1, "tokens": { "<canonical_url>": "<opaque token>" } }
```

- **`schema_version` is read on load.** An unrecognised value raises
  `TokenStoreError` with a "this CLI is older than your token store" message
  rather than guessing at the shape. It is one integer of forward-compat
  insurance and matches what npm, pip, and gh do.
- **Keys are canonicalised**: lowercase scheme and host, **port preserved
  verbatim** (default ports are *not* collapsed), trailing slash stripped, via
  `urllib.parse.urlsplit`. This catches the mixed-case-host and trailing-slash
  typos that would otherwise create phantom entries, without entering full
  RFC-3986 territory. `http://prod:8000` and `http://prod:8001` stay distinct.
- **Saves are atomic**: serialise → write to `<target>.tmp.<pid>.<random>` at
  mode `0600` → `os.rename()` over the target. `os.rename()` is atomic on POSIX,
  so a reader sees the old or the new file, never a partial one, and two
  concurrent `login`s against *different* servers cannot clobber each other's
  entries. The pid+random suffix keeps the two saves off the same temp path.
- **An empty-string token is never valid** — refused on write, treated as absent
  on read.
- **`logout` rewrites `tokens: {}` rather than deleting the file**, and a token
  rejected as stale is **not** auto-deleted — the user can inspect and remove it.

The file is human-readable JSON on purpose. Encrypting it needs a key-management
story; `0600` is the boundary v1 relies on.

### 3. `TokenStore` and `CredentialResolver` stay separate

Two modules, not one: the store answers "how is a token persisted?", the
resolver answers "which token do we use?". They change for different reasons and
are independently testable — the resolver's tests inject a `Mapping` for the
environment and a stubbed store, with no filesystem involved. There is no
`AuthState` class mixing I/O with policy, and the resolver does not own a
`TokenStore` instance.

### 4. Multi-profile support is reserved, not built

v1 ships the flat `{<url>: <token>}` shape. A future `--profile` flag bumps
`schema_version` to `2` and migrates entries to `tokens.<url>.<profile>` with a
`_default` profile for v1 data — mechanical, and the `TokenStore` surface
(`get` / `set` / `delete` / `canonicalise`) extends without breaking signatures.

## Consequences

- **CI has two supported non-interactive paths**: export a long-lived
  `STYRMIN_TOKEN`, or set `STYRMIN_USERNAME`/`STYRMIN_PASSWORD` and let each
  invocation mint its own session. The auto-login token is deliberately not
  persisted, so a CI runner leaves no credential on disk.
- **Adding a command requires no auth work.** Anything that calls `get_client()`
  inherits the whole ladder.
- **The store's write contract became a house pattern.** ADR-047's telemetry
  store copies it exactly (atomic temp + rename, `0600`/`0700`, XDG path); the
  reusable rule is written up in
  [`dev/guidelines/cyclopts.md`](../guidelines/cyclopts.md).
- **Auto-login costs one extra round-trip per invocation** and creates a session
  row per command. Acceptable for CI; `STYRMIN_TOKEN` is the path for anyone who
  cares.
- **A stale disk token produces a friendly two-line error, not a retry.** The
  CLI does not attempt re-authentication on `401`; it tells the user to run
  `login`.
- **`Session` / `Session token` / `Token store` are still absent from
  `CONTEXT.md`.** Deliberately deferred to a vocabulary-only change so a glossary
  edit would not gate a CLI feature. The terms are used consistently in code and
  in this ADR; the follow-up remains open.

## Alternatives Considered

- **Pre-baking the nested `{url: {profile: token}}` shape.** Rejected: pays a
  complexity tax in every read and test for a feature with no concrete demand;
  `schema_version` makes the later migration mechanical.
- **No version field.** Rejected: a later migration would have to sniff the shape
  with heuristics.
- **Using `Settings.server_address` verbatim as the key.** Rejected: a
  mixed-case host or trailing slash creates a second phantom entry for the same
  server.
- **Full RFC-3986 normalisation** (default-port collapse, percent-encoding, IDN).
  Rejected: drags in IPv6 and IDN corner cases for negligible benefit on a value
  users paste-configure once.
- **Letting the SDK resolve `STYRMIN_TOKEN` on its own.** Rejected: two
  independent readers of the same variable means the CLI's documented precedence
  is a lie in some code paths.
- **An `AuthState` god object.** Rejected: mixes policy with I/O and makes both
  hard to test.
- **Auto-deleting a token the server rejected.** Rejected: destroys evidence
  during debugging, and a transient `401` would silently log the user out.
