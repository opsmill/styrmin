# Quickstart — Unified Deployment Configuration Surface

**Feature**: 011-unified-deployment-config
**Audience**: developers implementing or reviewing slices of this feature.

## One-time setup (already done in the repo)

```bash
uv sync                           # backend + workspace deps
cd frontend && pnpm install       # frontend deps (idempotent)
uv run invoke pre-commit-install  # if not done yet
```

## Run the dev stack locally

```bash
uv run invoke dev                 # full stack: API, frontend, supporting services
```

This launches the backend on port 8000 and the frontend on port 5173.

Open `http://localhost:5173` and log in with the seeded admin user (`damien@opsmill.com`, password in `dev/local-creds`).

## Reach a deployment with mixed inherited / overridden state

The dev stack seeds at least one environment (`Production`) and a few deployments. To get one with the right shape for testing this feature:

```bash
# From repo root, while `uv run invoke dev` is running:
uv run styrmin deploy create \
    --environment Production \
    --driver helm-standard@3.2.0 \
    --name api-gateway-test \
    --parameter replicas=3 \
    --parameter log_level=info

# Then patch the scheduling block so the deployment differs from the env:
uv run styrmin deploy update api-gateway-test \
    --scheduling-resources-cpu-request=750m \
    --scheduling-tolerations='[{"key":"gpu","operator":"Exists","effect":"PreferNoSchedule"}]'
```

Now open `http://localhost:5173/deployments/api-gateway-test` — the Configuration tab is what this feature ships.

## Day-to-day development loop

### Adding a new section (slices 5–10)

1. Create the matching pair:
   - `frontend/src/components/deployment/configuration/sections/read/<X>Summary.tsx`
   - `frontend/src/components/deployment/configuration/sections/edit/<X>Section.tsx`
2. Export the Zod schema and add it to the drawer's aggregated form.
3. Wire `<X>Summary` into `ConfigurationTab.tsx` and `<X>Section` into the drawer's section list and `SectionNav`.
4. Add a vitest unit test for the section's schema validation.
5. Add the slice's `[ui-chromium]` E2E test under `backend/tests/e2e/configuration/`.
6. Run the E2E test locally **with `--pdb`** per CLAUDE.md:

   ```bash
   sleep infinity | uv run pytest backend/tests/e2e/configuration/test_drawer_<x>_edit.py -v -s --pdb 2>&1 | tee /tmp/pdb.log
   ```

7. Run frontend lint/format/test:

   ```bash
   cd frontend && pnpm lint && pnpm format:check && pnpm test
   ```

8. Run backend lint/format (E2E tests are Python):

   ```bash
   uv run invoke format lint
   ```

### Modifying `get_deployment.graphql` (slice 1, possibly slice 4)

If you add fields to the deployment query (parent env config, last-update event):

```bash
# 1) Update the .graphql file
# 2) Validate it parses against the live schema
uv run invoke validate-graphql

# 3) Regenerate SDK + frontend types
uv run invoke generate
```

CI fails if these aren't run; the pre-commit hook also fails locally.

### Removing the legacy SchedulingConfigDialog (slice 11)

```bash
rm -r frontend/src/components/deployment/scheduling/
# also remove the import and the "Scheduling" button from DeploymentDetailPage.tsx
cd frontend && pnpm test         # re-run unit tests
# then run every E2E in backend/tests/e2e/configuration/ to confirm no regression
```

## Manual smoke checks per slice

After each slice ships, the reviewer should be able to:

| Slice | Manual check |
|---|---|
| 1 | Configuration tab is the only tab between Overview and Pods; Driver Parameters chip row renders all parameters with correct values. |
| 2 | "Edit configuration" opens a right-side drawer; section nav rail is clickable; sticky footer reads "0 pending changes" with Discard + Review & apply both disabled. |
| 3 | Change CPU request in the Scheduling section, see the amber border and "from Xm" annotation; "Review & apply" enables and footer shows "1 pending change". |
| 4 | Confirmation dialog opens from "Review & apply"; diff shows the path-level change; Impact section lists "Pods will be recreated with new resource limits"; Apply & redeploy applies and pods restart. |
| 5 | Add an env var via the drawer; confirm it appears in the deployment's pods after redeploy. |
| 6 | Change DB size; observe expected impact text and persisted result. |
| 7 | Add a CIDR to IP allowlist; verify the ingress allowlist annotation is updated on the Kubernetes Ingress. |
| 8 | Add a service-name override; verify the Service object is renamed in the namespace. |
| 9 | Change a driver parameter via the drawer (e.g., `enable_pdb=false`); verify the resource is removed from the cluster. |
| 10 | Set a CPU resource override on the `rate-limiter` component; verify the component's Deployment resource gets the new request/limit. |
| 11 | "Scheduling" header button is gone; the legacy dialog is unreachable; every section's E2E is still green. |

## Where to look for things

| Question | Location |
|---|---|
| Where is the diff computed? | `frontend/src/lib/config-diff.ts` |
| Where is the impact rule table? | `frontend/src/lib/impact-rules.ts` |
| Where is inheritance computed? | `frontend/src/lib/config-inheritance.ts` |
| Where does the form's domain model come from? | `UpdateDeploymentInput` (generated) + `frontend/src/lib/deployment-input.ts::deploymentConfigToInput` |
| Why is the Scheduling dialog still there mid-feature? | By design — slice 11 removes it after every section ships. See `research.md` R-011. |
| Why no backend changes? | `UpdateDeploymentInput` already supports every field. See `plan.md` Constitution Check + `contracts/update-deployment-mutation.md`. |
