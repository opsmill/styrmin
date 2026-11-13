# Quickstart: validating the service ingress override

**Feature**: [spec.md](spec.md) | **Contracts**: [contracts/graphql-and-manifest.md](contracts/graphql-and-manifest.md)

This guide shows how to prove the feature end to end. It holds no implementation code. The end-to-end tests of `tasks.md` automate every scenario.

## Prerequisites

- `vcluster` and `docker` on the PATH. The end-to-end fixtures create their own disposable cluster (AGENTS.md); `uv run invoke dev` is not needed for the tests.
- `uv sync` and `cd frontend && pnpm install`.
- The new versions of the `infrahub` and `generic-app` drivers from this change.
- For the Tailscale part of SC-005 only: a cluster with the Tailscale operator and a tailnet. Not available in the test fixtures; the result is recorded by hand.

## 1. Unit and contract checks (fast)

```bash
uv run invoke format lint
uv run invoke test
uv run pytest cli/tests -q          # run the CLI and SDK tests one after the other:
uv run pytest python_sdk/tests -q   # both folders have a tests/conftest.py, so one pytest run cannot load both
cd frontend && pnpm test && pnpm lint && pnpm exec tsc -b && pnpm build && cd ..
uv run styrmin export graphql-schema schema.graphql   # no diff expected after regeneration
uv run invoke generate                                # no diff expected after regeneration
uv run invoke validate-graphql
git status --short                                    # no diff expected after the three commands above
```

Expected: no failure, no uncommitted diff in `schema.graphql`, the SDK and the frontend types.

## 2. User story 1: one service moves, the other stays (API)

1. Deploy `infrahub` on the new driver version in environment `lab`, on a cluster with class `traefik` and suffix `example.com`.
2. Save the Ingress objects of the namespace: `kubectl get ingress -n <namespace> -o yaml > before.yaml`.
3. Set the override for `task-manager`: class `tailscale`, suffix `tailnet.example.ts.net`, through `updateDeployment` or `styrminctl deployments apply`.
4. Save the Ingress objects again as `after.yaml`.

Expected:

- The `task-manager` Ingress has `spec.ingressClassName: tailscale`, the host `task-manager-lab.tailnet.example.ts.net`, no `traefik.ingress.kubernetes.io/*`, external-dns or Cloudflare annotation, and no `spec.tls`.
- The `infrahub` Ingress is identical in `before.yaml` and `after.yaml` (SC-002).
- Reading the service through GraphQL gives the new host and `ingressClassOverridden: true`.
- Clearing the override gives the cluster class and suffix again.
- The `task-manager` Ingress has the labels `styrmin/environment_id` and `styrmin/deployment_id`, like the chart Ingress. On a cluster with a dedicated ingress controller, the controller serves only an Ingress with `styrmin/environment_id`.
- Traffic, on a cluster with a dedicated ingress controller: a request to the controller with `Host: task-manager-lab.example.com` answers HTTP 200 before the override and after it is cleared. With the override class `tailscale`, the same host and the overridden host answer HTTP 404 through that controller, because the Ingress has another class. Whether a Tailscale controller serves the overridden host is not covered.

## 3. User story 2: no override

Deploy `generic-app`. Expected: exactly one Ingress for the `app` service (SC-006), with the resolved class, the annotations that the chart Ingress carried before, and both the application address and the readable host. With a dedicated ingress controller, both hosts answer HTTP 200 through it. Delete the deployment: the Ingress is gone.

Deploy a driver with two external services. Expected: exactly one Ingress carries the application address (FR-002 as changed by research D-003).

## 4. User story 3: UI

Open the deployment, then the Settings tab, and edit the settings. In the section Services, the drawer offers the fields "Ingress class for <service>" and "FQDN suffix for <service>" for each external service only, and the button "Clear ingress override for <service>". Set both fields for `task-manager` and use Review & apply. Expected: the deployment redeploys, and the Networking card of the Settings tab lists `task-manager` at the new host under class `tailscale`, marked Overridden. The same fields exist in the group "Service ingress overrides" of the deploy form.

## 5. User story 4: refused requests

- Set an override on `infrahub` (internal): expect `SERVICE_INGRESS_NOT_BUILT` naming the service.
- Store an override on `task-manager`, then change the driver version to one that declares it `internal`: expect `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED`, and check that no pod restarted and the override is still stored.

## 6. Environment with a dedicated ingress controller (FR-008)

Turn on `dedicated_ingress` for the environment and override one service. Expected: the other Ingresses have no `spec.ingressClassName` and the annotation set to the controller implementation; the overridden one has the override class. Send a request through the controller with the `Host` header of a service without an override: HTTP 200. The end-to-end fixtures have a dedicated Traefik, so the tests of steps 2 and 3 do this.

## 7. Existing Infrahub deployment (not known in the PRD)

Upgrade a running `infrahub` deployment from the previous driver version (`infrahub-enterprise` 4, or `infrahub` 5) to the new driver version (`infrahub-enterprise` 5, or `infrahub` 6). The previous version is in git history: `git show ad1e5673^:driver/examples/infrahub-enterprise/driver.styrmin.yml` and `values.j2.yml`.

1. Load the previous driver version, deploy on it, and wait until the deployment is running.
2. Load the new driver version. Start a loop that lists the Ingresses of the namespace every second, and a loop that sends one request per second to `/api/health` through the environment's ingress controller with the header `Host: task-manager-<environment name>.<fqdn suffix>`.
3. Change the deployment to the new driver version with `update_version` (the SDK) or the upgrade dialog, and keep both loops running until the deployment is running and the Ingress list has not changed for a minute.

Record: whether the chart's Ingress `styrmin-task-manager` is removed, when `styrmin-svc-task-manager` appears, whether the task manager address stops answering, and for how long. Do this with the operator interval of the end-to-end fixtures (5 seconds) and with the default (60 seconds). Expected: the address answers HTTP 200 before and after, and the record states any interval in which it does not. Measured on a local vCluster with the label on the Ingress: no interval at the 5-second pass (two runs), about 12 and about 7 seconds of HTTP 404 at the 60-second pass (two runs).

The results are in `e2e-evidence.md`, sections "T062: upgrade of a running Infrahub deployment, Tailscale, and the default timer interval" (without the label) and "The label defect: fix, traffic checks and the upgrade measurement repeated" (with the label). The throwaway script that ran these steps is not in the repository.

## Evidence

Test output and the recorded results go into `specs/033-service-ingress-override/e2e-evidence.md` during implementation.
