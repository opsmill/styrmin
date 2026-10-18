# Data Model: Load an Application Driver from a Driver Directory of a Git Repository

**Feature**: [spec.md](spec.md) | **Research**: [research.md](research.md)

No database schema change and no Alembic revision: `source_path` already exists on `applicationdriverversion` and is part of the unique index `uq_application_driver_version_identity` ([`db/models.py`](../../backend/styrmin_backend/db/models.py)).

## Driver directory (value)

The folder of a git repository that holds a driver's `driver.styrmin.yml`, `values.j2.yml` and `actions.py`, given relative to the repository root.

| Form | Example | Meaning |
| --- | --- | --- |
| Given by the admin | `./drivers/infrahub/`, `drivers//infrahub`, `""`, `.` | Any of the forms in [research.md R-005](research.md#r-005-one-stored-form-of-a-driver-directory-and-the-values-refused-before-the-clone) |
| Stored | `drivers/infrahub` | Segments joined with `/`, no leading `./`, no trailing `/`, no empty or `.` segment |
| Repository root | `None` | Stored as no value in `source_path` |

Validation, in order (FR-006, FR-007):

1. Remove surrounding whitespace.
2. Refuse a backslash, a NUL character, or a leading `/`.
3. Drop empty and `.` segments.
4. Refuse a `..` segment.
5. No segment left → `None`.

A refusal raises `DriverLoadingError` (code `VALIDATION_ERROR`) before the clone, and names the given value and the rule.

After the clone (FR-008, FR-009):

- The resolved driver directory and the resolved paths of the three driver files MUST be inside the resolved clone root. This check runs for root loads too.
- The driver directory MUST be a folder and MUST hold `driver.styrmin.yml`.

## `GitSource` (driver service model, extended)

[`services/driver/models/structure/source.py`](../../backend/styrmin_backend/services/driver/models/structure/source.py)

| Field | Type | Change |
| --- | --- | --- |
| `type` | `"git"` | unchanged |
| `repository` | `str` | unchanged |
| `branch` | `str` | unchanged |
| `token` | `str` | unchanged |
| `driver_directory` | `str \| None` | **new**, the stored form; `None` for the repository root |

`LocalSource` is unchanged.

## `ApplicationDriverVersion` (database row, behaviour change only)

| Column | Git row loaded from the root | Git row loaded from a driver directory | Local row |
| --- | --- | --- | --- |
| `source_type` | `git` | `git` | `local` |
| `source_repository` | repository URL | repository URL | `""` |
| `source_branch` | branch | branch | `NULL` |
| `source_path` | `NULL` (unchanged) | driver directory, for example `drivers/infrahub` (**new**) | absolute server path (unchanged) |
| `source_commit_sha` | commit of the whole repository | commit of the whole repository | `NULL` |
| `content_hash` | `NULL` | `NULL` | SHA-256 of the three files |

Identity: the unique index covers `application_driver_id`, `source_type`, `source_repository`, `source_branch`, `source_path`, `version`, `content_hash` and `source_commit_sha`, with `NULLS NOT DISTINCT`. So:

- A reload of a root driver at the same commit finds the existing row, as today.
- A reload of a driver directory at the same commit, written in any form, finds the existing row, because the stored form is the same.
- Two driver directories at the same commit make two rows, also when the driver name and `version` are the same.

## Action deployment in Prefect (registration, extended)

Built by `ActionsWorkflowBuilder` ([`services/user.py`](../../backend/styrmin_backend/services/user.py)) and saved by `PrefectManager.register_user_action` ([`workflows/manager.py`](../../backend/styrmin_backend/workflows/manager.py)).

| Property | Root driver version (unchanged) | Driver version from a driver directory (new) |
| --- | --- | --- |
| Deployment name | `User Action: <action> (<driver>@<short commit>)` | `User Action: <action> (<driver>@<short commit> <directory digest>)`, where the digest is the first 7 hex characters of SHA-256 of the stored driver directory |
| Tags | `application/<driver>`, `version/<supported>`, `hook/<hook>`, `mode/<mode>`, `fingerprint/<short commit>` | the same, plus `directory/<driver directory>` |
| Pull steps | `git_clone` (commit pinned, `clone_directory_name` = `<repo>-<short commit>`) | `git_clone` as for root, then `set_working_directory` with `directory: <clone_directory_name>/<driver directory>` |
| Entrypoint | `actions.py:<function>` | unchanged |

Lookup (`get_user_action_deployment_id`): with a driver directory, the tag filter includes `directory/<driver directory>`. Without one, results that carry any `directory/` tag are dropped before the newest is picked.

## GraphQL `ApplicationDriverVersion` (output, behaviour change only)

`sourcePath: String` already exists. It now returns the driver directory for git driver versions loaded from one, and stays `null` for git driver versions loaded from the root.

## E2E test repository `driver-collection` (test fixture, new)

```text
driver-collection.git (branch master)
└── drivers/
    ├── simple-app/   # driver/examples/simple-app with the chart location and spec.info rewrite
    └── db-test/      # driver/examples/db-test with the chart location rewrite
```
