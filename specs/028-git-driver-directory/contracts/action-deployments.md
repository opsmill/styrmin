# Contract: Prefect deployments of driver actions loaded from a driver directory

**Feature**: [spec.md](../spec.md) | FR-004, FR-010 | **Research**: [R-001](../research.md#r-001-how-prefect-sets-the-working-directory-of-a-driver-action-and-what-it-puts-on-the-import-path), [R-002](../research.md#r-002-the-existing-set_directory_pull_step-helper-writes-a-path-that-does-not-exist-in-the-actions-container), [R-003](../research.md#r-003-two-driver-versions-from-one-commit-replace-each-others-actions)

## Pull steps

Driver version loaded from `drivers/infrahub` of `git://git-server/driver-collection.git` at commit `0123456789abcdef…`:

```python
[
    {
        "prefect.deployments.steps.git_clone": {
            "repository": "git://git-server/driver-collection.git",
            "branch": None,
            "commit_sha": "0123456789abcdef…",
            "clone_directory_name": "driver-collection-0123456",
            "credentials": "{{ prefect.blocks.github-credentials.user-github-token }}",
        }
    },
    {
        "prefect.deployments.steps.set_working_directory": {
            "directory": "driver-collection-0123456/drivers/infrahub",
        }
    },
]
```

- The `set_working_directory` path is relative. It resolves against the folder `git_clone` cloned into, which is the image's working directory (`/source` for the default `styrmin` image).
- A driver version loaded from the repository root has only the `git_clone` step, unchanged.
- Entrypoint: `actions.py:<function>`, unchanged.

Effect at run time (Prefect 3.8.6): the flow runs with the working directory `<image working directory>/driver-collection-0123456/drivers/infrahub`, and Prefect's script loader puts only that folder on `sys.path`. `import helpers` in `actions.py` finds `drivers/infrahub/helpers.py`; a module at the repository root or in `drivers/shared/` is not found.

## Deployment name and tags

| | Root driver version | Driver version from `drivers/infrahub` |
| --- | --- | --- |
| Name | `User Action: setup (infrahub@0123456)` | `User Action: setup (infrahub@0123456 5f3c2a1)` (`5f3c2a1` = first 7 hex characters of SHA-256 of `drivers/infrahub`) |
| Tags | `application/infrahub`, `version/<supported>`, `hook/setup`, `mode/pre`, `fingerprint/0123456` | the same, plus `directory/drivers/infrahub` |

## Lookup

`PrefectManager.get_user_action_deployment_id(application, version, hook, mode, fingerprint=None, driver_directory=None)`:

- `driver_directory` given: filter `tags.all_` includes `directory/<driver_directory>`.
- `driver_directory` `None`: filter as today, then drop deployments with a tag that starts with `directory/`.
- Newest first, as today.

Callers pass `driver_version.source_path` when `driver_version.source_type == "git"`, else `None`:

- `instantiate_application` in [`services/applications.py`](../../../backend/styrmin_backend/services/applications.py)
- the create and upgrade paths in [`services/reconciliation/remediation.py`](../../../backend/styrmin_backend/services/reconciliation/remediation.py)

## Unit tests

- `backend/tests/unit/workflows/test_git_source_commit_pinning.py` (extended): the two-step pull steps above; the relative `set_working_directory` path (replaces the `/opt/prefect/` expectation); a root definition keeps one step.
- `backend/tests/unit/workflows/test_action_driver_directory.py` (new): run Prefect's `run_steps` with a `set_working_directory` step against a folder tree in `tmp_path`, then `load_flow_from_entrypoint("actions.py:<flow>")`. An action that imports a sibling module loads; an action that imports a module from the tree's root fails with `ModuleNotFoundError`.
- `backend/tests/unit/workflows/test_user_action_registration.py` (new or the existing manager tests): registration name and tags with and without a driver directory; lookup with a driver directory matches only its tag; lookup without one drops `directory/` deployments.
