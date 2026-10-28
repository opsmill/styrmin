# ADR-089: The Code That Reads, Checks and Renders a Driver Lives in the SDK, and the Backend Imports It

**Status**: Accepted
**Date**: 2026-10-28
**Decision-makers**: proposed by Fatih Acar on Slack on 2026-10-28, in a direct conversation with no link; recorded as decided in the brief of #23
**Source**: specs/032-styrmin-driver-cli/spec.md, specs/032-styrmin-driver-cli/research.md (R-001, R-002, R-011, R-012, R-020);
[issue #23](https://github.com/opsmill/styrmin/issues/23) and its
[brief](https://github.com/opsmill/styrmin/issues/23#issuecomment-6466328637)
**Related**: [ADR-081](0081-local-driver-actions-check-their-files-at-the-driver-path.md) (local driver load and action check)

## Context

A driver author finds most errors in an application driver only when a running Styrmin loads
or deploys it (#23). Issue #23 asks for a command that checks and renders a driver on the
author's machine, with no server, database or cluster.

Before this decision, the code that reads, checks and renders a driver directory was in the
backend, and it imported the backend's dependencies:

- the renderer (`agent/service/kubernetes/resources/builders/application.py`) imports Prefect;
- the local driver provider shares `services/driver/provider.py` with the git provider, which
  imports dulwich, loguru and the server settings;
- the driver model imports `ReplicaDeclaration` from the context model, whose validators import
  five validator modules under `services/`, loguru and the backend's errors.

`styrminctl` is a thin client over the GraphQL API (`CONTEXT.md`), so it cannot hold these
checks. An offline check script, `check_driver.py` in the `creating-styrmin-drivers` agent skill,
holds a copy of the loader rules of Styrmin 0.1.54 and falls out of date with each release.

## Decision drivers

- One set of rules: the command, the server's load and the agent's render must apply the same
  code, so that a change to a rule applies to all three.
- The command must run with no server, database, cluster or network.
- The server's behaviour, messages and import paths must not change.

## Considered options

1. Move the driver format code to the SDK, and make the backend import it.
2. Copy the rules into the SDK or into the command.
3. Put the command in `styrminctl`, which would then import the backend.

## Decision

Option 1. A new package, `styrmin_sdk.driver_format` (`python_sdk/src/styrmin_sdk/driver_format/`),
holds:

- `errors`: `ServiceError`, the base of every backend service error, and the errors that the moved
  code raises. `ServiceError` moves so that the moved errors keep the base that the GraphQL error
  extension recognises (`api/errors.py`);
- `models`: the driver model, with the three file names of a driver directory as a parameter
  (`DriverFileNames`) instead of a read of the server settings;
- `reading`: the parsers, the deserializers, the file loader and the local driver provider;
- `checks`: the template, retired-filter, env var doc, backup and action checks;
- `rendering`: the Jinja environment, its filters and `render_values`;
- `context`: the context model (`GlobalContext` and its sub-models), the resolver, the FQDN
  functions, the config validators and their errors, the parameter resolver, the naming helpers
  and `build_service_entries`.

The backend depends on `styrmin-sdk`. Every moved backend module stays at its path as a module
that re-exports the SDK names, so every import of the backend, of its tests and of the drivers'
`actions.py` (`styrmin_backend.actions.GlobalContext`) keeps working, with the same class
objects. The git provider, the provenance fingerprint, hook resolution and everything that reads
the database stay in the backend.

The backend's `DriverDirectory` is a subclass that passes the server's `STYRMIN_DRIVER_*`
settings to the SDK model. The agent's `render_value_template` keeps its Prefect `@task` and
calls `render_values`.

The moved code logs with the standard library. `styrmin_backend/__init__.py` installs a handler
that forwards the `styrmin_sdk` logger to loguru (`styrmin_backend/logging_bridge.py`), so the
warnings keep reaching the server's log and the tests' loguru sinks.

The SDK keeps `requires-python = ">=3.12"`. The root ruff configuration lints `python_sdk/` for
Python 3.12 (`per-file-target-version`), so syntax that Python 3.12 cannot parse is rejected.

## Consequences

- Good, because `styrmin-driver` and the server apply one copy of the rules.
- Good, because no import path or class of the backend changes, and one message only: for a
  `driver.styrmin.yml` that is not a mapping, "Provided data is not of expected type: ..." now
  names the class `DriverSpec` without its module, where it named
  `styrmin_backend.services.driver.models.resources.driver.DriverSpec` before the move. The
  backend test suite passed unchanged after the move.
- Bad, because the backend now depends on the SDK, and the SDK depends on Jinja2 and packaging,
  which every SDK user installs.
- Bad, because a test that patches an attribute of a moved module at its backend path no longer
  reaches the code that the SDK calls. None existed at the time of the move.
- Bad, because the moved code was never checked by the root ruff rules: the backend's ruff
  configuration does not extend the root one. The root configuration lists the rules that the
  moved code does not meet for the moved folders, to be reviewed later.
- Bad, because CI runs the SDK tests on Python 3.14 only, so the Python 3.12 minimum is checked
  for syntax and not at run time.

## Confirmation

- `uv run invoke test` passes with no change to an expected message.
- `python_sdk/tests/driver_format/test_no_backend_imports.py` checks that the SDK modules load
  without `styrmin_backend`, Prefect, dulwich, loguru, sqlmodel or pydantic-settings.
- `backend/tests/unit/services/driver/test_loaders.py` checks that the server settings still
  choose the file names.
- `backend/tests/unit/test_logging_bridge.py` checks that an SDK warning reaches a loguru sink.

## More information

The command `styrmin-driver` that uses this package is described in
specs/032-styrmin-driver-cli/ and `docs/docs/reference/styrmin-driver.md`.
