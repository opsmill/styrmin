# Research: `styrminctl` Authentication

This document resolves every `[NEEDS CLARIFICATION]` from `spec.md` and records the design decisions that shape Phase 1.

## R1 — Token expiry in `whoami`

**Question (from spec)**: Does the backend `login` mutation return a token expiry timestamp, and if so should `whoami` print a `Session expires at …` line?

**Decision**: **No.** `whoami` will not print an expiry line. FR-003 stands as written.

**Rationale**: Direct inspection of `schema.graphql` shows the `LoginResult` type exposes only `token: String!` and `user: User!`. No `expiresAt` field. `CurrentUser` likewise does not surface an expiry. The backend may have an internal expiry, but it is not part of the GraphQL contract, so the CLI cannot display it without a schema change — and a schema change is out of scope per the PRD on #234.

**Alternatives considered**:

- *Adding `expiresAt` to `LoginResult`*: would require a backend schema change, a propagation test, and a coordinated SDK regeneration — explicitly outside this feature's scope.
- *Inferring expiry from a 401/UNAUTHENTICATED response time*: lossy, racy, and noisier than the already-planned "Run `styrminctl login` to refresh." hint in FR-008.

**Impact**: NEEDS CLARIFICATION resolved. No spec change needed.

## R2 — Token-store JSON forward-compat shape

**Question (from spec)**: Should v1 ship the simple `{<canonical_url>: <token>}` shape with a documented `schema_version` field, or pre-bake the nested `{<canonical_url>: {<profile>: <token>}}` shape with a default profile name?

**Decision**: **Simple shape with a `schema_version` field.** The on-disk JSON is:

```json
{
  "schema_version": 1,
  "tokens": {
    "<canonical_url>": "<token>"
  }
}
```

`schema_version: 1` is read on load; an unrecognised value produces a friendly single-line "this CLI is older than your token store; please re-login or upgrade" error. When a future `--profile` flag lands, it bumps `schema_version` to `2` and migrates entries to `tokens.<canonical_url>.<profile>` with a `_default` profile for v1 data.

**Rationale**:

- The simple shape exactly matches v1 behaviour. Nesting under a default profile that users never see is dead structure that complicates `TokenStore` reads and tests.
- A `schema_version` field is one integer of forward-compat insurance and is industry-standard for JSON credential stores (npm, pip, gh).
- Migration is mechanical: load → if `schema_version == 1` then `for url, tok in tokens.items(): tokens[url] = {"_default": tok}` → bump to 2 → save.

**Alternatives considered**:

- *Pre-baked nested shape*: pays complexity tax for a feature that has no concrete user demand yet.
- *No version field*: drift-prone; later migrations would have to sniff the shape with heuristics.

**Impact**: Captured in `data-model.md`. NEEDS CLARIFICATION resolved.

## R3 — CONTEXT.md vocabulary update

**Question (from spec)**: Should `Session`, `Session token`, and `Token store` be added as first-class entries in `CONTEXT.md` as part of this feature?

**Decision**: **Defer to a separate vocabulary-only follow-up.** Mirror the grilling-session decision recorded in the idea brief.

**Rationale**:

- `CONTEXT.md` is structured by domain (clusters, environments, deployments, drivers, instances, reconciliation, etc.). Session / token / store are auth-infrastructure concepts that originate from ADR-024 and were intentionally not surfaced when #179 shipped.
- Adding them inside this feature would mix a glossary change with a CLI change, complicating review and risking either being held up by the other.
- The cost of deferral is bounded: this spec uses `Session`, `Session token`, and `Token store` consistently and tags `Token store` as "new, CLI-local" in Key Entities, so the terminology does not drift in code.

**Follow-up**: open a separate small PR (or a vocabulary-only spec) that adds these three entries to `CONTEXT.md` once #234 ships. Track via the existing Open Question in this spec; the next CLI/auth contributor can pick it up.

**Impact**: NEEDS CLARIFICATION resolved. No spec change needed.

## R4 — Canonical-URL canonicalisation

**Decision (from PRD / grilling)**: lowercase scheme and host, preserve port verbatim, strip trailing slash. Implemented with `urllib.parse.urlsplit` for safety.

```python
def canonicalise(server_address: str) -> str:
    parts = urlsplit(server_address)
    scheme = (parts.scheme or "http").lower()
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port is not None else ""
    path = parts.path.rstrip("/")
    return f"{scheme}://{host}{port}{path}"
```

**Rationale**: catches the common mixed-case-host typo and the trailing-slash variant without entering full RFC-3986 territory (default-port collapse, percent-encoding normalisation, IDN handling) — all of which would add edge cases for negligible benefit on a CLI users paste-configure.

**Alternatives considered**:

- *Use `Settings.server_address` verbatim*: rejected during grilling (mixed-case host creates phantom store entries).
- *Full RFC-3986 normalisation*: overkill; drags in IDN/IPv6 corner cases.

## R5 — Hidden password prompt

**Decision**: Use stdlib `getpass.getpass(prompt="Password: ")`.

**Rationale**: It is the de-facto standard for hidden TTY input in Python, handles `EOFError` on non-interactive stdin cleanly (raised as a regular Python exception we can wrap with a one-line CLI error), and avoids pulling in a third-party dependency. Cyclopts does not (today) ship a first-class hidden-prompt primitive; `getpass` integrates cleanly with our Cyclopts command function signature.

**Edge case**: when stdin is not a TTY (CI without `STYRMIN_USERNAME`/`PASSWORD`), `getpass` reads from stdin and prints a warning to stderr. We accept this: in real CI users should use the auto-login path; falling back to interactive `login` in a no-TTY context is rare and warning-worthy.

## R6 — `whoami` source-attribution scheme

**Decision**: `get_client()` returns `(StyrminClient, TokenSource)` where `TokenSource` is an enum-like literal with these values:

- `"env"` → rendered as `Authenticated via: env (STYRMIN_TOKEN)`
- `"file"` → rendered as `Authenticated via: token file (<path>)`
- `"auto-login"` → rendered as `Authenticated via: auto-login (STYRMIN_USERNAME)`

Source is never the token itself. The CLI command for `whoami` accepts the tuple and prints the source on a separate line.

**Rationale**: keeps the rendering string out of `CredentialResolver` (which only returns the enum) and out of the SDK (which has no concept of "where the token came from"). Single ownership: `commands/auth.py::whoami` formats; `auth/resolver.py` decides; `auth/token_store.py` knows nothing of `whoami`.

## R7 — Error rendering shape

**Decisions**:

- Backend authentication errors (`StyrminAuthenticationError`) → single-line message + non-zero exit. No traceback. Wording locked by spec: `Not logged in. Run \`styrminctl login\` or set STYRMIN_TOKEN.` and (for stale-disk-token) an additional `Run \`styrminctl login\` to refresh.` line.
- CLI-side `TokenStoreError` (new, CLI-only `Exception` subtype) covers: corrupt JSON, unknown `schema_version`, chmod-failure, parent-directory not writable. Each renders as a single line that names the file path.
- Asymmetric env vars: a typed CLI-side error rendered with the missing variable name.

**Rationale**: §IV says typed errors at the service layer; CLI control-flow errors are not service-layer concerns. Centralising rendering in `cli/src/styrminctl/errors.py` lets the Cyclopts top-level handler do `except` → `sys.exit(<msg>)` cleanly.

## R8 — Deep-module rationale (`TokenStore`, `CredentialResolver`)

Both modules pass the deep-module test: significant functionality behind a small, stable, testable interface. They are independently useful and independently testable; combining them would muddle "where does the token come from?" (resolver) with "how is the token persisted?" (store) — two concerns that change for different reasons.

`TokenStore` surface (load/save/delete + canonical-URL helper) is stable across the lifetime of the feature; profile support (R2) extends it without breaking signatures.

`CredentialResolver` surface (a single `resolve(settings, env, token_store) -> (token, source)`) is pure logic; tests inject env and a stubbed `TokenStore`.

Anti-patterns avoided: no "AuthState" god class that mixes I/O and policy; no resolver-with-an-internal-`TokenStore`-instance that becomes hard to test.

## R9 — Existing-code touchpoints

Surveyed before planning:

- `cli/src/styrminctl/config.py` already strips trailing slash from `server_address` — `canonicalise()` still re-runs the rule defensively.
- `cli/src/styrminctl/client.py::get_client()` is the single point where credentials enter the CLI today; all command modules import it. Centralising the resolver here covers every command.
- `cli/src/styrminctl/cli_commands.py` registers subapps with `app.command("…:cluster_app", name="clusters")`; the new `auth_app` follows the same pattern.
- SDK `StyrminClient.__init__` already accepts `token=` and reads `STYRMIN_TOKEN` itself. The CLI must NOT double-read the env var — when we pass a resolved token explicitly, the SDK uses it; we never let it silently fall back.
- `python_sdk/src/styrmin_sdk/resources/auth.py` exposes `login`, `logout`, `current_user`, `change_password`. We consume the first three; `change_password` is out-of-scope.

## R10 — Backwards-compatible `get_client()` (from critique E1)

`get_client() -> StyrminClient` keeps its existing signature so the seven existing command modules (`clusters`, `environments`, `drivers`, `deployments`, `backups`, `backup_storage_locations`, `tasks`) need no edit. A new sibling `get_auth_context() -> AuthContext` is the only consumer of source attribution; it is called from `whoami` exclusively. Both helpers delegate to the same `CredentialResolver` so behaviour stays unified.

## R11 — Atomic token-store save (from critique E2)

`TokenStore.save()` MUST be atomic: serialise → write to `<target>.tmp.<pid>.<random>` with mode `0600` → `os.rename()` over the target. `os.rename()` is atomic on POSIX; this guarantees that two concurrent `login`s against different canonical URLs cannot clobber each other's entries, which would have violated FR-013 / SC-005. Unit test `test_concurrent_saves_preserve_both_entries` covers the race.

## R12 — Testing strategy

- **`TokenStore` unit suite** (`cli/tests/auth/test_token_store.py`): round-trip; canonical-URL collision check; missing-file is no error; corrupt-JSON raises `TokenStoreError`; mode `0600` on file, `0700` on parent; multiple servers coexist; `schema_version` mismatch raises `TokenStoreError`; atomic-save preserves both entries under concurrent writes.
- **`CredentialResolver` unit suite** (`cli/tests/auth/test_resolver.py`): one assertion per precedence rung (env / file / auto-login / none); asymmetric env-var error; empty `STYRMIN_TOKEN` treated as unset; `STYRMIN_TOKEN` wins over disk; auto-login wins over disk.
- **CLI tests** (`cli/tests/commands/test_auth_commands.py`): `login` happy path with mocked SDK; `login` non-TTY EOF gives a friendly single-line error (per critique E5); `logout` no-op when no store; `whoami` source line per rung; friendly-error rendering for `StyrminAuthenticationError`.
- **E2E** (`backend/tests/e2e/test_cli_auth.py`): see `quickstart.md` for the scenario blueprint. Single scenario, `@pytest.mark.api_only(reason=…)`.

Per AGENTS.md, no `--reruns` markers and no mocked backend in the E2E.
