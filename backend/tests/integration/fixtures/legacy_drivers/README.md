# Legacy driver templates

## Overview

This directory holds unchanged copies of the `values.j2.yml` templates of three example drivers, taken before issue #457 moved container `command` and `args` overrides to post-render patches:

| Directory | Source template | Driver version at copy time |
|-----------|-----------------|-----------------------------|
| `simple-app/` | `driver/examples/simple-app/values.j2.yml` | `2` |
| `infrahub/` | `driver/examples/infrahub/values.j2.yml` | `3` |
| `infrahub-enterprise/` | `driver/examples/infrahub-enterprise/values.j2.yml` | `2` |

These templates call the `component_command` and `component_args` Jinja filters to pass a component's `command` and `args` overrides to chart values.

## Why they are kept

The SC-005 parity test (`backend/tests/integration/test_container_override_migration_parity.py`) renders the same stored config twice:

- with these legacy templates and a copy of the old filter code that the test module keeps;
- with the migrated driver template and the post-render patches.

The test then compares the component container's `command` and `args`. It shows that a deployment that moves to a migrated driver version runs with the same `command` and `args` as before. See SC-005 in `specs/archive/022-post-render-container-overrides/spec.md` and D-011 in `specs/archive/022-post-render-container-overrides/research.md`.

## Rules

- Do not edit or migrate these files. They must stay byte-identical to the pre-migration templates, or the parity test no longer compares against what users ran.
- These files are not drivers. The directory has no `driver.styrmin.yml`, so the driver loader does not read it.
- After the filters are retired, these templates fail to render in the production Jinja environment. Only the parity test renders them, with its own copy of the old filters.
