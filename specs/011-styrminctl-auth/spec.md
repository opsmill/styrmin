# Feature Specification: `styrminctl` Authentication — `login` / `logout` / `whoami` + Persistent Token Store

**Feature Branch**: `011-styrminctl-auth`
**Created**: 2026-05-17
**Status**: Implemented
**Input**: PRD published as a comment on [opsmill/styrmin#234](https://github.com/opsmill/styrmin/issues/234#issuecomment-4470324108). Seed idea brief at `.specify/idea-brief.md` (note: that file may also hold an unrelated brief; the PRD comment is authoritative for this feature).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Interactive `login` persists a token; subsequent commands just work (Priority: P1)

A platform engineer points `STYRMIN_ADDRESS` at a deployed Styrmin backend, runs `styrminctl login --username <name>`, types her password (input hidden), and sees `Logged in to <address> as <name>`. Every subsequent `styrminctl` command — in the same shell, in a fresh shell, on the same machine — authenticates automatically against that backend without re-typing credentials. `styrminctl logout` ends the session and removes the local credential.

**Why this priority**: Without this slice, `styrminctl` is unusable against any post-#179 backend. Every other journey assumes the persistent token exists. There is no smaller useful slice to ship first.

**Independent Test**: Run `styrminctl login --username <seeded-user>` against an end-to-end backend with the password supplied on stdin. Assert exit 0 and the local token file exists with mode `0600`. Open a fresh subprocess with only `STYRMIN_ADDRESS` set (no `STYRMIN_TOKEN`, no other env), run `styrminctl clusters list`, and assert it succeeds. Run `styrminctl logout` and assert the entry is deleted.

**Acceptance Scenarios**:

1. **Given** a backend reachable at `STYRMIN_ADDRESS` and no prior login on this machine, **When** the user runs `styrminctl login --username alice` and supplies a valid password (typed hidden), **Then** the CLI prints `Logged in to <address> as alice`, persists the returned token to `${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/token` with mode `0600` (parent directory mode `0700`), under an entry keyed by the canonical server URL, and exits 0.
2. **Given** a token store entry exists for the current `STYRMIN_ADDRESS`, **When** the user runs `styrminctl whoami`, **Then** the CLI prints the username, display name, effective role, and a separate `Authenticated via: token file (<path>)` line, never printing the token value itself, and exits 0.
3. **Given** a stored token, **When** the user runs `styrminctl logout`, **Then** the CLI invokes the backend `logout` mutation on a best-effort basis, deletes the token-store entry for the current server even if the network call fails, prints `Logged out of <address>`, and exits 0.
4. **Given** no prior token file or directory exists, **When** the user runs `styrminctl login --username alice`, **Then** the CLI creates the directory with mode `0700` and the file with mode `0600` before writing, and succeeds.
5. **Given** the user has tokens for two distinct servers, **When** they switch `STYRMIN_ADDRESS` between the two and run `whoami` for each, **Then** each invocation reports the identity associated with that server without cross-contamination.

---

### User Story 2 - Non-interactive auto-login via `STYRMIN_USERNAME` + `STYRMIN_PASSWORD` (Priority: P2)

A CI job sets `STYRMIN_ADDRESS`, `STYRMIN_USERNAME`, and `STYRMIN_PASSWORD` from secret storage. It runs an authenticated `styrminctl` command. The CLI logs in transparently for that single invocation, uses the resulting token in-process, and writes nothing to disk. Subsequent jobs on the same shared runner cannot read or reuse the credentials.

**Why this priority**: Required for CI to use the CLI at all. Independently testable from Story 1: the auto-login path does not touch the token store and does not run the interactive prompt.

**Independent Test**: In a subprocess whose environment has `STYRMIN_USERNAME` and `STYRMIN_PASSWORD` set but no `STYRMIN_TOKEN` and no pre-existing token file under XDG, run an authenticated command (e.g. `styrminctl clusters list`). Assert exit 0 and assert the token file is *not* created on disk afterwards.

**Acceptance Scenarios**:

1. **Given** both `STYRMIN_USERNAME` and `STYRMIN_PASSWORD` are set and no `STYRMIN_TOKEN`, **When** any authenticated `styrminctl` command runs, **Then** the CLI calls the backend `login` mutation once for this invocation, uses the resulting token in-process, succeeds, and leaves the on-disk token store unchanged.
2. **Given** only one of `STYRMIN_USERNAME` / `STYRMIN_PASSWORD` is set, **When** any command runs, **Then** the CLI exits non-zero with a single-line message naming the missing variable, and does not attempt an unauthenticated request.
3. **Given** a token store entry *and* `STYRMIN_USERNAME` + `STYRMIN_PASSWORD` are present for the same server, **When** any authenticated command runs, **Then** the env-var auto-login wins, the disk token is left untouched, and the command succeeds as the env-var identity.
4. **Given** both `STYRMIN_TOKEN` and `STYRMIN_USERNAME` + `STYRMIN_PASSWORD` are set, **When** any authenticated command runs, **Then** `STYRMIN_TOKEN` wins, no auto-login round-trip happens, and the command succeeds as that token's identity.

---

### User Story 3 - Friendly failure mode when not logged in or token is invalid (Priority: P3)

A user with no credentials runs an authenticated `styrminctl` command, or a user whose stored token has been revoked or expired does the same. In both cases the CLI prints a single human-readable line, exits non-zero, and never raises a Python traceback. The stale token file is preserved so the user can debug it.

**Why this priority**: The friendliness of the failure mode is the difference between an adopted CLI and one users complain about. Independently testable from Stories 1 and 2.

**Independent Test**: Run any authenticated command with no `STYRMIN_TOKEN`, no token-store entry, and no `STYRMIN_USERNAME`/`STYRMIN_PASSWORD`. Assert stderr is exactly the advertised single line and the exit code is non-zero. Then write a junk token into the store, run the same command, assert the same kind of single-line message, and assert the junk token file is still present on disk after the failure.

**Acceptance Scenarios**:

1. **Given** no credentials of any kind, **When** the user runs an authenticated command, **Then** the CLI prints exactly `Not logged in. Run \`styrminctl login\` or set STYRMIN_TOKEN.`, exits non-zero, and emits no Python traceback.
2. **Given** a token-store entry whose value the backend rejects with `UNAUTHENTICATED`, **When** the user runs an authenticated command, **Then** the CLI prints the same single-line message plus a `Run \`styrminctl login\` to refresh.` hint, exits non-zero, and the stale token entry remains on disk.
3. **Given** the token store file exists but contains invalid JSON, **When** the user runs an authenticated command, **Then** the CLI prints a single-line message naming the file and the parse problem, exits non-zero, and does not auto-delete the file.

---

### Edge Cases

- **Both `STYRMIN_TOKEN` and `STYRMIN_USERNAME`/`PASSWORD` set** → `STYRMIN_TOKEN` wins; the auto-login round-trip is skipped entirely.
- **Disk token entry *and* env-var credentials for the same server** → env-var auto-login wins; disk token is left untouched.
- **`logout` while offline / backend unreachable** → CLI swallows the `auth.logout()` network error, still deletes the local entry, prints `Logged out of <address>`, exits 0.
- **`STYRMIN_TOKEN` set to the empty string** → treated as unset, so empty env defaults do not masquerade as a real token.
- **Mixed-case host or trailing slash in `STYRMIN_ADDRESS`** → resolves to the same token-store entry as the lower-case, no-trailing-slash variant (lowercasing of scheme and host; port preserved verbatim; trailing slash stripped).
- **Token store directory exists but is world-readable** → the CLI reasserts mode `0700` on the directory before writing; if the chmod fails the CLI exits non-zero with a clear message and does not write the file.
- **Token store file exists but is corrupt JSON** → the CLI prints a single-line message naming the file, exits non-zero, does not auto-delete the file; user can remove and re-`login`.
- **`whoami` with no credentials at all** → friendly "Not logged in" message, non-zero exit, no traceback.
- **Multiple servers** → `prod` and `staging` tokens coexist in one file because their canonical-URL keys differ.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a `styrminctl login` command. Optional `--username` argument; when omitted the CLI prompts for it. The password is always prompted with input hidden. On success the CLI calls the backend `login` mutation, persists the returned token via the token store, and prints `Logged in to <server_address> as <username>`. *Verified by*: subprocess test driving stdin; asserts token-store entry written and exit 0.
- **FR-002**: System MUST provide a `styrminctl logout` command. It calls the backend `logout` mutation on a best-effort basis (network and `UNAUTHENTICATED` errors swallowed), then deletes the token-store entry for the current `STYRMIN_ADDRESS`. Succeeds silently when no entry is stored. *Verified by*: running `logout` twice; the second invocation exits 0 with no error.
- **FR-003**: System MUST provide a `styrminctl whoami` command. It calls the backend `currentUser` query; on success it prints `username`, `display_name`, `role`, and a separate `Authenticated via: <source>` line where `<source>` is one of `env (STYRMIN_TOKEN)`, `token file (<path>)`, or `auto-login (STYRMIN_USERNAME)`. The token value MUST never be printed. When unauthenticated the command exits non-zero with the friendly "Not logged in" message. *Verified by*: parametrised test, one case per precedence rung, asserting the source string.
- **FR-004**: System MUST resolve credentials for every authenticated invocation using this exact precedence (highest wins): (1) `STYRMIN_TOKEN` environment variable, (2) token-store entry for the canonical server URL, (3) auto-login derived from `STYRMIN_USERNAME` + `STYRMIN_PASSWORD` (used in-process, never persisted), (4) unauthenticated (only `login` and `--help` work). *Verified by*: resolver unit test with one assertion per rung plus the empty case.
- **FR-005**: When `STYRMIN_USERNAME` and `STYRMIN_PASSWORD` are both set, System MUST auto-login on every invocation and MUST NOT persist the token to disk. When exactly one of the two is set, System MUST exit non-zero with a message naming the missing variable. *Verified by*: two unit tests — happy path asserts no file write; asymmetric-env case asserts message and non-zero exit.
- **FR-006**: The token store MUST be a JSON map keyed by canonical server URL. Canonicalisation rule: lowercase scheme and host, preserve port verbatim, strip trailing slash. *Verified by*: unit test mapping `http://Prod:8000/` and `http://prod:8000` to the same key, and `http://prod:8001` to a different key.
- **FR-007**: The token-store file MUST live at `${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/token`, be created with file mode `0600` and parent directory mode `0700`. *Verified by*: end-to-end test asserting `stat` permission bits after `login`.
- **FR-008**: When the SDK raises an authentication error (backend `UNAUTHENTICATED` or `INVALID_CREDENTIALS`), the CLI MUST render a single-line friendly message and exit non-zero. The CLI MUST NOT print a Python traceback for these errors. The CLI MUST NOT auto-delete a stale token-store entry on this path. *Verified by*: unit test injecting the SDK auth error and asserting on stderr shape and exit code.
- **FR-009**: Passwords MUST never be written to disk, never logged at any level, and never echoed at the prompt. *Verified by*: assertion that the `login` flow uses a hidden-input helper; assertion that no logger emits the password value.
- **FR-010**: `styrminctl login` and `styrminctl logout` MUST succeed end-to-end when no prior token file exists. *Verified by*: end-to-end test exercising `login` from an empty XDG directory; unit test asserting `logout` is a no-op when the file is absent.
- **FR-011**: Users MUST be able to authenticate from non-interactive contexts (CI, scripts) by setting only `STYRMIN_ADDRESS`, `STYRMIN_USERNAME`, and `STYRMIN_PASSWORD`. *Verified by*: FR-005 happy-path test plus documentation in `cli/README.md` describing the flow.
- **FR-012**: `styrminctl login` MUST print the resolved `STYRMIN_ADDRESS` it is authenticating against, so the user can detect a misconfigured environment before they type a password. *Verified by*: capturing stdout of `login` and asserting the address appears verbatim.
- **FR-013**: Tokens for distinct backends MUST coexist in one token-store file without overwriting each other. *Verified by*: unit test that calls `login` against two canonical URLs and verifies both entries survive.

### Key Entities

- **Session** *(existing, backend)*: server-side row created by the backend `login` mutation, identified by an opaque token. Lifetime is governed by the backend (see ADR-024). This feature does not change the Session entity.
- **Session token** *(existing, SDK and backend)*: opaque bearer string returned by `login`, carried as `Authorization: Bearer <token>` on subsequent requests. Already plumbed through the SDK transport; this feature plumbs it through the CLI as well.
- **Token store** *(new, CLI-local)*: a per-user JSON file at `${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/token` (file mode `0600`, directory mode `0700`) that maps canonical server URL → session token. It is a local credential cache, not a domain entity; the backend has no knowledge of it. The token store replaces the current ad-hoc "re-export `STYRMIN_TOKEN` in every shell" workflow.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user with valid credentials can authenticate once with `styrminctl login` and then run every authenticated CLI command in the same shell, and in subsequent shells on the same machine, without re-supplying credentials, for the entire lifetime of the backend session.
- **SC-002**: 100% of non-interactive invocations that set `STYRMIN_USERNAME` and `STYRMIN_PASSWORD` against a reachable backend succeed authenticated, and leave no credential file on disk after the run.
- **SC-003**: 0% of CLI authentication failures render as a Python traceback. Every authentication failure path produces a single human-readable line and a non-zero exit code.
- **SC-004**: The token-store file permissions are `0600` and parent-directory permissions are `0700` after any successful `login` on every supported platform, verified automatically.
- **SC-005**: Tokens for distinct backends never collide: writing tokens against two different server URLs and reading them back returns the correct token for each.
- **SC-006**: A first-time user can go from "no Styrmin credentials on this machine" to a successful authenticated `styrminctl clusters list` in under 30 seconds, assuming they know their username, password, and the backend address.

## Assumptions

- Backend session tokens from the `login` mutation remain valid until the user logs out or the backend expires the session; the CLI does not need to handle proactive refresh in v1. Expiry is surfaced via the friendly `Run \`styrminctl login\` to refresh.` message in FR-008.
- The `currentUser` query returns at least `username`, `displayName`, and the user's role string (consistent with the SDK's `CurrentUserCurrentUser` shape).
- POSIX target. Users run the CLI under a UNIX user account where `~/.local/share` is writable and `0700`/`0600` semantics are honored. Windows support is out of scope for v1.
- The existing `STYRMIN_TOKEN` semantics from the SDK are unchanged; the CLI just stops *failing* to pass a token when one is available.
- The auth model itself is unchanged from #179 / ADR-024. This feature is strictly about how `styrminctl` *uses* credentials, not how the backend issues or validates them.
- No new dependencies are required: `cyclopts`, `pydantic-settings`, and the existing SDK are already present; `getpass`, `json`, and `pathlib` are stdlib.

## Dependencies

- The backend exposes the `login`, `logout`, and `currentUser` GraphQL operations (delivered by #179) and enforces authentication on protected mutations (delivered by #187). This feature consumes them; it does not change them.
- The Python SDK already raises a typed authentication error for `UNAUTHENTICATED` / `INVALID_CREDENTIALS` and already accepts `token=` and `STYRMIN_TOKEN`. The CLI relies on those behaviours unchanged.

## Out of Scope

- `styrminctl change-password` — deferred. The SDK already exposes the underlying operation; this feature ships only `login` / `logout` / `whoami`.
- OS keychain / Secret Service / macOS Keychain Access integration.
- SDK-side token persistence (the SDK deliberately stays in-memory).
- Multi-account / `--profile` switching as an explicit flag; per-server-URL keying covers most of this implicitly.
- SSO / OIDC / browser-based login flows.
- `styrminctl token print` / `styrminctl token rotate`.
- API tokens / service-account tokens distinct from user session tokens.
- A `--token <value>` CLI flag (env var only for v1).
- Windows-specific path handling and credential storage.

## Open Questions

- [NEEDS CLARIFICATION: Does the backend `login` mutation return a token expiry timestamp, and if so should `whoami` print a `Session expires at …` line? If no expiry is returned, FR-003 stands as written; if one is, the spec and `whoami` output need to include it.]
- [NEEDS CLARIFICATION: Forward-compatibility shape of the token-store JSON. v1 ships `{<canonical_url>: <token>}`. If a future `--profile` flag lands, we will want `{<canonical_url>: {<profile>: <token>}}`. Should v1 ship the simple shape with a documented `schema_version` field to make migration cheap, or pre-bake the nested shape now with a default profile name?]
- [NEEDS CLARIFICATION: Should `Session`, `Session token`, and `Token store` be added as first-class entries in `CONTEXT.md` as part of this feature, or in a separate vocabulary-only follow-up?]
