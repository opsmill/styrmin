# ADR-084: The Record Command Deletes Only the Environments Whose Ids It Recorded, and Asks Before It Deletes Any Other

**Status**: Accepted
**Date**: 2026-10-21
**Decision-makers**: Fatih Acar
**Source**: specs/archive/031-recorded-feature-demos/research.md (R-014),
specs/archive/031-recorded-feature-demos/spec.md (Clarifications, session of 2026-10-21; FR-009,
FR-010, FR-022), specs/archive/031-recorded-feature-demos/data-model.md ("Created environments
file"); [PR #540](https://github.com/opsmill/styrmin/pull/540)
**Related**: [ADR-073](0073-kubernetes-objects-named-and-found-by-record-id.md) (objects found by
record id), [ADR-082](0082-recorded-demos-reuse-e2e-page-objects.md) (the recorded demos)

## Context

Each recorded demo (`uv run invoke record`, ADR-082) creates environments with fixed, readable
names on the `local` cluster of the demo stack, for example `network-lab` and `network-lab-clone`
(FR-008). Environment names are unique on a cluster, so a demo cannot create its environment while
an earlier run's environment with the same name exists. A failed demo keeps its environments for
inspection (FR-010), so the next run of that demo has to delete them before its setup (FR-009).

The first design (research R-014) looked up each of the demo's names on the cluster and deleted the
environments it found. The review of PR #540 on 2026-10-21 found that this also deletes an
environment with one of these names that the command did not create, for example one that a
developer made by hand on the demo stack.

## Decision drivers

- A failed earlier run never blocks the next run of a demo.
- The command never deletes an environment that someone else created without asking first.
- A run without a terminal, which cannot ask, changes nothing.

## Considered options

1. Delete every environment that has one of the demo's names (the design of research R-014).
2. Record the id of each environment that the command creates, and delete without asking only the
   environments whose ids are recorded.

## Decision

We chose option 2.

- The command records the id and name of each environment it creates in
  `$XDG_STATE_HOME/styrmin/demo-environments.json` (by default under `~/.local/state`), keyed by the
  demo stack URL (`backend/tests/e2e/demos/ledger.py`, `CreatedEnvironments`). The file lives
  outside the repository, because one demo stack serves every checkout on the host. It is written to
  a temporary file and then renamed.
- Before the first demo, the command lists the existing environments that have a selected demo's
  names. When one of them is not in the file, it prints their names and ids and asks
  `Delete them? [y/N]`. A yes records them in the file. Without a yes, or without a terminal, the
  command stops with exit code 2 before any change.
- When a demo deletes its environments, before its setup or after its recording, it refuses to
  delete an environment whose id is not in the file, for example one created after the question. It
  fails with an error that names the environment.
- `uv run invoke record --delete-environments` deletes the environments of the selected demos under
  the same rules (FR-022).
- The setup demo, added after a review of the videos on 2026-10-21, creates the environment of demo 1
  in the Styrmin UI and leaves it to demo 1. The command records its id in the file like the id of any
  other environment it creates. When demo 1 runs after the setup demo in the same run, it does not
  delete that environment before its setup; it deletes it after its recording, as before.

An environment created again by `uv run invoke reset` has a new id, so ids left in the file never
match it.

## Consequences

- Good, because an environment that a developer created with a demo's name is deleted only after
  the developer confirms it.
- Good, because ids, not names, decide what the command may delete, as ADR-073 asks for the
  Kubernetes objects that Styrmin creates.
- Bad, because an environment that an earlier version of the command created, before the file
  existed, is not in the file, so the next run asks before it deletes it.
- Bad, because a run without a terminal, for example from a script, stops when it finds such an
  environment. The developer deletes or renames it in the Styrmin UI first, or runs the command on a
  terminal and answers y.

Option 1 was rejected because it deletes environments that the command did not create, with no
question.

## Confirmation

- `backend/tests/unit/demos/test_ledger.py`: the file is under the XDG state directory; `remember`
  and `forget` keep each stack apart; a damaged file names its path.
- `backend/tests/unit/demos/test_main.py`:
  `test_an_environment_the_command_did_not_create_stops_the_run_unless_confirmed`,
  `test_a_confirmed_environment_is_deleted_before_the_setup` and
  `test_a_demo_refuses_to_delete_an_environment_that_appeared_after_the_question`.

## More information

[Environments the command deletes](../guides/local-demo.md#environments-the-command-deletes) in the
local demo guide.
