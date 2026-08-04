# Quickstart: Verify No-Op Deployment Updates

## Manual verification (against a running stack)

```bash
# 1. First apply — creates the deployment.
uv run styrminctl deployments apply -f app.yaml --environment local
#   → created <name>
#     1 created, 0 updated, 0 unchanged, 0 failed

# 2. Re-apply the identical manifest — clean no-op.
uv run styrminctl deployments apply -f app.yaml --environment local
#   → unchanged <name>
#     0 created, 0 updated, 1 unchanged, 0 failed
#   exit code 0
```

Confirm server-side that the no-op produced no side effects (no new instance, no new task):

```bash
# Instance count for the deployment must be identical before/after step 2.
# Task count for the deployment must be identical before/after step 2.
```

## Automated verification

```bash
# Service + SDK + CLI units
uv run pytest backend/tests/unit -k "update_deployment or noop"
uv run pytest python_sdk/tests/test_deployments.py
uv run pytest cli/tests/test_deployments.py

# Functional / propagation (the changed mutations)
uv run pytest backend/tests/functional/graphql/test_deployment.py

# E2E (definition of done) — run with --pdb per AGENTS.md, record PASS evidence
sleep infinity | uv run pytest backend/tests/e2e/test_deployments_apply.py::test_apply_unchanged_manifest_is_noop -v -s --pdb 2>&1 | tee /tmp/pdb.log
```

## What "done" looks like

- Re-applying an unchanged manifest: `unchanged`, exit 0, **0** new instances, **0** new tasks (SC-001/002/005).
- Config-only change → exactly 1 reconcile; version-only change → exactly 1 upgrade (SC-003).
- No-op apply to a FAILED deployment → 0 reconciles (SC-004).
- `uv run invoke format lint` clean; E2E observed PASS locally with recorded node id / command / timestamp / cluster / `PASSED` line.
