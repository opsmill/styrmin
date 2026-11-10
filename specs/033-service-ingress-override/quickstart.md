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
cd frontend && pnpm test
uv run styrmin export graphql-schema schema.graphql   # no diff expected after regeneration
uv run invoke generate                                # no diff expected after regeneration
uv run invoke validate-graphql
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

## 3. User story 2: no override

Deploy `generic-app`. Expected: exactly one Ingress for the `app` service (SC-006), with the resolved class, the annotations that the chart Ingress carried before, and both the application address and the readable host. Delete the deployment: the Ingress is gone.

Deploy a driver with two external services. Expected: exactly one Ingress carries the application address (FR-002 as changed by research D-003).

## 4. User story 3: UI

Open the deployment, Configuration, Service overrides. Only external services are listed. Set both fields for `task-manager`, save. Expected: the deployment redeploys, and the Networking summary lists `task-manager` at the new host under class `tailscale`, marked as overridden; `infrahub` is marked as inherited. The same fields exist on the deploy form.

## 5. User story 4: refused requests

- Set an override on `infrahub` (internal): expect `SERVICE_INGRESS_NOT_BUILT` naming the service.
- Store an override on `task-manager`, then change the driver version to one that declares it `internal`: expect `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED`, and check that no pod restarted and the override is still stored.

## 6. Environment with a dedicated ingress controller (FR-008)

Turn on `dedicated_ingress` for the environment and override one service. Expected: the other Ingresses have no `spec.ingressClassName` and the annotation set to the controller implementation; the overridden one has the override class.

## 7. Existing Infrahub deployment (not known in the PRD)

Upgrade a running `infrahub` deployment to the new driver version. Record: whether the task manager address stops answering, and for how long. The result goes into the migration guide.

## Evidence

Test output and the recorded results go into `specs/033-service-ingress-override/e2e-evidence.md` during implementation.
