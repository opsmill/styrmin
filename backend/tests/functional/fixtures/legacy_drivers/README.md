# Legacy infrahub drivers

## Overview

This directory holds unchanged copies of two example drivers, taken before issue #202 retired the `replicas_server` and `replicas_task_worker` parameters:

| Directory | Source directory | Driver version at copy time |
|-----------|------------------|-----------------------------|
| `infrahub-v4/` | `driver/examples/infrahub/` | `4` |
| `infrahub-enterprise-v3/` | `driver/examples/infrahub-enterprise/` | `3` |

Each copy has the three files that the driver loader reads: `driver.styrmin.yml`, `values.j2.yml` and `actions.py`. These driver versions declare the `replicas_server` (default `1`) and `replicas_task_worker` (default `2`) parameters, and their `values.j2.yml` passes the two values to the `replicas` value of the chart's `infrahubServer` and `infrahubTaskWorker` sections.

## Why they are kept

The retired-parameter upgrade tests (`backend/tests/functional/graphql/test_infrahub_replica_parameter_upgrade.py`) need a deployment on a driver version that still declares the two parameters. They load these copies, then change the deployment to the current example driver version, which declares the counts as `components.server.replicas` and `components.task-worker.replicas` instead. The tests check that:

- a deployment that kept the default parameter values moves to the new driver version, and each component keeps its replica count (SC-004);
- a deployment with a changed parameter value is rejected with an error that names the parameter and its value (SC-005).

See SC-004 and SC-005 in `specs/archive/023-per-component-replicas/spec.md`, and D-013 and D-014 in `specs/archive/023-per-component-replicas/research.md`.

## Rules

- Do not edit these files. They must stay byte-identical to the driver versions that users deployed, or the upgrade tests no longer start from what users ran.
- Ruff does not lint or format this directory (`extend-exclude` in `backend/pyproject.toml`), so `uv run invoke format` does not rewrite `actions.py`. yamllint skips it through the `/backend/tests/**/fixtures/` entry in `.yamllint.yml`.
- ty still type-checks `actions.py`. A change to the `styrmin_backend.actions` functions that these files import shows up in `uv run invoke lint`.
- These are complete drivers, so a test can load each directory with `get_local_driver_loader`. The tests that check every example driver read `driver/examples/` only, so they do not load these copies.
