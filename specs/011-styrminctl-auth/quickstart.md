# Quickstart: `styrminctl` Authentication (`011-styrminctl-auth`)

## Local development walkthrough

Prerequisites: working Styrmin backend on `http://localhost:8000` (e.g. via `uv run invoke dev`) with at least one seeded user.

```bash
# Build / install the CLI in editable mode (already part of `uv sync`)
uv sync

# Point the CLI at your backend
export STYRMIN_ADDRESS=http://localhost:8000

# Verify "not logged in" path
uv run styrminctl whoami
# → stderr: "Not logged in. Run `styrminctl login` or set STYRMIN_TOKEN."
# → exit non-zero

# Interactive login
uv run styrminctl login --username alice
# → prompts hidden for password
# → stdout: "Authenticating against http://localhost:8000 …"
# → stdout: "Logged in to http://localhost:8000 as alice"
# → token persisted under $XDG_DATA_HOME (or $HOME/.local/share)/styrminctl/token

# Verify identity + source attribution
uv run styrminctl whoami
# → stdout:
#     Username: alice
#     Display name: Alice Example
#     Role: PLATFORM_ENGINEER
#     Authenticated via: token file (/home/alice/.local/share/styrminctl/token)

# Verify file permissions
stat -c '%a %n' ~/.local/share/styrminctl ~/.local/share/styrminctl/token
# → 700 .../styrminctl
# → 600 .../styrminctl/token

# Exercise any other authenticated command
uv run styrminctl clusters list

# Log out
uv run styrminctl logout
# → stdout: "Logged out of http://localhost:8000"
```

## Non-interactive (CI) flow

```bash
export STYRMIN_ADDRESS=http://prod:8000
export STYRMIN_USERNAME=ci-bot
export STYRMIN_PASSWORD=…   # from CI secret store

uv run styrminctl deployments list
# CLI auto-logs-in in-process; token NOT written to disk.

ls -la ~/.local/share/styrminctl/token  # absent or unchanged
```

## E2E scenario blueprint

The single E2E that gates this feature.

- **File**: `backend/tests/e2e/test_cli_auth.py`
- **Markers**: `@pytest.mark.ci`, `@pytest.mark.api_only(reason="Drives the styrminctl subprocess; no UI flow. The [ui-chromium] variant would re-execute the same subprocess and the same SDK login path with no incremental coverage.")`
- **Fixtures**: shared vcluster + backend fixtures from existing e2e suite; a temporary `XDG_DATA_HOME` directory per test (`tmp_path`) to isolate the token store from the developer's real one.
- **Test name**: `test_cli_login_persists_token_and_subsequent_command_succeeds`

### Scenario steps

1. **Seed a user** through the existing E2E user-seeding fixture (mirroring `backend/tests/e2e/test_user_management.py` pattern). Capture `username`, `password`.
2. **Run `styrminctl login`** in a subprocess with:
   - `STYRMIN_ADDRESS` pointing at the port-forwarded backend.
   - `XDG_DATA_HOME=<tmp_path>`.
   - No `STYRMIN_TOKEN`, no `STYRMIN_USERNAME`/`PASSWORD`.
   - `--username <seeded>` on the command line; `password\n` fed via stdin.
3. **Assert**:
   - Exit code 0.
   - Stdout contains `Logged in to <STYRMIN_ADDRESS> as <seeded>`.
   - `<tmp_path>/styrminctl/token` exists.
   - `oct(os.stat(file).st_mode & 0o777) == "0o600"`.
   - Parent directory mode `0o700`.
   - JSON parses; `schema_version == 1`; the canonical-URL key contains a non-empty token.
4. **Run an authenticated command** in a fresh subprocess (`styrminctl clusters list`) with the same `STYRMIN_ADDRESS` and `XDG_DATA_HOME` and no other env. Assert exit 0 and that output is well-formed (cluster list, possibly empty).
5. **Run `styrminctl whoami`** in a fresh subprocess. Assert exit 0; stdout contains the seeded username and the `Authenticated via: token file (...)` line.
6. **Run `styrminctl logout`**. Assert exit 0; stdout contains `Logged out of <STYRMIN_ADDRESS>`.
7. **Re-read the token store**. Assert `tokens` is `{}` (the canonical key is absent).
8. **Run `styrminctl whoami` again**. Assert non-zero exit and stderr matches the friendly "Not logged in" line.

### Local PASS evidence (recorded at implementation time per §V)

The implementer MUST record in `tasks.md` (or the PR body):

- pytest node ID, e.g. `backend/tests/e2e/test_cli_auth.py::test_cli_login_persists_token_and_subsequent_command_succeeds[api-chromium]`
- Exact pytest command run.
- ISO 8601 timestamp of the PASS.
- Cluster identifier (vcluster fixture id + kubeconfig path).
- Verbatim `PASSED …` line from pytest output.

## Verifying coverage of the spec FRs

| FR | Covered by |
|---|---|
| FR-001 (`login`) | E2E step 2-3; `test_auth_commands.py::test_login_happy_path` |
| FR-002 (`logout`) | E2E step 6-7; `test_auth_commands.py::test_logout_is_noop_without_prior_token` |
| FR-003 (`whoami`) | E2E step 5; `test_auth_commands.py::test_whoami_source_per_rung` |
| FR-004 (precedence) | `test_resolver.py` — the 9-row decision table in `contracts/credential-precedence.md` |
| FR-005 (env-var auto-login + asymmetric error) | `test_resolver.py` rows 4 / 7 / 8 |
| FR-006 (canonical URL) | `test_token_store.py::test_canonicalisation_collisions` |
| FR-007 (file path + permissions) | E2E step 3; `test_token_store.py::test_permissions_after_save` |
| FR-008 (friendly auth errors) | `test_auth_commands.py::test_friendly_error_on_unauthenticated` |
| FR-009 (password handling) | `test_auth_commands.py::test_password_never_logged_or_echoed` |
| FR-010 (no prior file) | E2E step 2 + `test_token_store.py::test_first_save_creates_dir_and_file` |
| FR-011 (CI auth) | `test_resolver.py` row 4 + cli/README.md doc |
| FR-012 (login prints address) | `test_auth_commands.py::test_login_prints_resolved_address` |
| FR-013 (multiple servers coexist) | `test_token_store.py::test_two_servers_dont_collide` |
