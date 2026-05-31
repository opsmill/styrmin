# Quickstart: `styrminctl deployments apply`

**Feature**: 009-deployments-apply

This document is the user-facing walkthrough for the `apply` command. It is written so a platform engineer who has never used the feature can read it once and have a working pipeline.

## Prerequisites

- `styrminctl` installed and configured (`STYRMIN_SERVER_ADDRESS` set, or a working `~/.styrmin/config.toml`).
- An Application Driver registered for the deployment you want to manage (e.g., `acme/my-driver`).
- A target environment (and cluster, if the environment name is not unique) already provisioned.

## Step 1 — Author your first manifest

```yaml
# deployment.yaml
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: my-app
spec:
  driver: acme/my-driver
  version: "1.2.3"
  environment: production
  cluster: my-cluster      # optional; required only if environment name is ambiguous
  config:
    log_level: info
    feature_x_enabled: true
  parameters:
    replicas: 3
```

## Step 2 — Apply it

```console
$ styrminctl deployments apply -f deployment.yaml
created my-app
1 created, 0 updated, 0 failed
$ echo $?
0
```

The deployment is now submitted. By default, `apply` returns immediately after submission — use `--wait` (Step 5) if you need to block until reconciliation completes.

## Step 3 — Re-apply after a change

Edit `deployment.yaml`, change `log_level: info` to `log_level: debug`, then:

```console
$ styrminctl deployments apply -f deployment.yaml
updated my-app
0 created, 1 updated, 0 failed
```

The same command updates the existing deployment. `config` and `parameters` are **fully replaced** with the manifest's values — there is no merge, so removing a key from the manifest removes it on the deployment.

## Step 4 — Apply a directory of manifests

```text
manifests/
├── frontend.yaml
├── backend.yaml
└── worker.yaml
```

```console
$ styrminctl deployments apply -f manifests/
created frontend
updated backend
created worker
2 created, 1 updated, 0 failed
```

Files are processed in sorted-filename order. Multi-document YAML (`---`-separated) and multiple `-f` flags work the same way:

```console
$ styrminctl deployments apply -f frontend.yaml -f backend.yaml
$ styrminctl deployments apply -f combined.yaml         # several documents in one file
```

## Step 5 — Block until terminal state with `--wait`

```console
$ styrminctl deployments apply -f deployment.yaml --wait
updated my-app
0 created, 1 updated, 0 failed
```

With `--wait`, the command does not return until the deployment reaches `RUNNING` (or a terminal failure state).

## Step 6 — Override fields from CI

A common pipeline:

```console
$ STYRMIN_VERSION="1.4.0" styrminctl deployments apply -f manifests/
```

Every manifest's `spec.version` is overridden with `1.4.0`. To target staging instead of production from the same files:

```console
$ STYRMIN_ENVIRONMENT="staging" styrminctl deployments apply -f manifests/
```

CLI flags win over env vars:

```console
$ STYRMIN_VERSION="1.4.0" styrminctl deployments apply --version 1.5.0 -f manifests/
# every manifest deployed at 1.5.0
```

## Step 7 — Handle batch failures

If one manifest fails (driver mismatch, missing required field, network error), `apply` continues processing the others and exits non-zero:

```console
$ styrminctl deployments apply -f manifests/
created frontend
failed backend: driver mismatch (manifest=acme/v2, existing=acme/v1); driver changes require delete-and-recreate
updated worker
1 created, 1 updated, 1 failed
$ echo $?
1
```

Suitable for a CI step:

```yaml
- name: Apply Styrmin manifests
  run: styrminctl deployments apply -f manifests/
```

The non-zero exit code fails the pipeline.

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `manifest deployment.yaml: unknown field at top level: 'foo'` | typo or extra field at the top of the YAML | remove the field or check the spec's allowed fields |
| `manifest deployment.yaml: name is required (set in manifest, env var, or CLI flag)` | `metadata.name` missing and no `--name` / `STYRMIN_NAME` provided | add the field to the manifest, or pass `--name` |
| `manifest deployment.yaml: environment 'staging' exists in multiple clusters: [a, b]; specify --cluster or spec.cluster` | env name ambiguous across clusters | add `spec.cluster` or pass `--cluster` |
| `--name cannot be combined with multiple manifests` | `--name` passed with `-f <dir>` or several `-f` flags | drop `--name`, or apply one manifest at a time |
| `manifest deployment.yaml: driver mismatch (manifest=X, existing=Y); driver changes require delete-and-recreate` | driver field changed between two applies | revert the driver field, or delete the deployment first |

## SDK equivalent

The CLI is a thin wrapper. The same flow from Python:

```python
import asyncio
from styrmin_sdk import StyrminClient

async def main():
    async with StyrminClient(server_address="...") as client:
        outcomes = await client.deployments.apply_files(["manifests/"])
        for o in outcomes:
            print(f"{o.action} {o.name}")

asyncio.run(main())
```

## What `apply` does **not** do (v1)

- **Does not delete deployments missing from a directory.** Deletion is still an explicit `styrminctl deployments delete` step.
- **Does not support `--dry-run`** or diff output. Validation happens locally before any backend call, so typos are caught early, but no preview of state changes is generated.
- **Does not support recursive directory traversal.** `-f <dir>` reads only the immediate `.yaml`/`.yml` files.
- **Does not support `kind` other than `Deployment`.**
- **Does not export existing deployments to manifests.**
- **Does not parallelise the batch.** Manifests are processed sequentially.
