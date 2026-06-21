# Contract: `styrminctl deployments apply`

This contract defines the user-facing CLI surface for the `apply` command — every flag, every supported invocation pattern, every output format, and every exit code. Changes to this surface are public-API changes.

## Synopsis

```text
styrminctl deployments apply -f <file_or_dir> [-f <file_or_dir>...]
                             [--name <name>]
                             [--version <version>]
                             [--environment <name>]
                             [--cluster <name>]
                             [--wait]
```

## Flags

| Flag | Repeatable | Env var | Overrides | Notes |
|---|---|---|---|---|
| `-f <path>` | **yes** | — | — | path to a YAML file or to a directory of YAML files; at least one `-f` is required |
| `--name <name>` | no | `STYRMIN_NAME` | `metadata.name` | refused with batch input (more than one manifest) |
| `--version <version>` | no | `STYRMIN_VERSION` | `spec.version` | applies to all manifests in the batch |
| `--environment <name>` | no | `STYRMIN_ENVIRONMENT` | `spec.environment` | applies to all manifests in the batch |
| `--cluster <name>` | no | `STYRMIN_CLUSTER` | `spec.cluster` | applies to all manifests in the batch |
| `--wait` | no | — | — | block until each successfully-submitted deployment reaches a terminal state |

## Override precedence

For each of `name`, `version`, `environment`, `cluster`: **CLI flag > environment variable > manifest field**.

Required-at-resolve-time fields (`name`, `driver`, `version`, `environment`) must be set by *some* source. Missing required values fail before any backend call is made.

## Input modes

| Form | What it does |
|---|---|
| `apply -f a.yaml` | apply a single manifest |
| `apply -f a.yaml -f b.yaml` | apply two manifests |
| `apply -f manifests/` | apply every immediate `.yaml`/`.yml` file in the directory, sorted by filename |
| `apply -f a.yaml -f manifests/` | combine — files and directories may be mixed across `-f` flags |
| `apply -f combined.yaml` (multi-doc) | apply each `---`-separated document independently |

Recursive directory traversal is **not** supported in v1. Stdin is **not** supported.

## Output format

### Without `--wait`

For each manifest, exactly one status line is written to stdout in processing order:

```text
created <name>
updated <name>
failed <name>: <reason>
```

After all manifests, exactly one summary line is written to stdout:

```text
<N> created, <M> updated, <K> failed
```

### With `--wait`

Submission and terminal status are reported on **two separate lines per deployment** (stdout streams cannot be edited after writing — see X1 in the design critique). For each manifest, in processing order:

1. On submission: `submitted <name>` (or `failed <name>: <reason>` if validation/submission itself failed).
2. On terminal state: `running <name>` (success) or `failed <name>: <reason>` (terminal failure or timeout) — emitted once the deployment reaches a terminal state during `--wait` polling.

After all manifests have settled, the same single summary line is written, using **post-wait counts** (a deployment that submitted successfully but failed to become `RUNNING` counts as `failed` in the summary).

```text
submitted my-app
running my-app
0 created, 1 updated, 0 failed
```

If a version-upgrade phase fails after a successful config update on an existing deployment, the `failed <name>: <reason>` line MUST say so explicitly: `failed <name>: config/parameters were updated; version upgrade failed: <error>`. This warns the operator that the deployment is in a partially-updated state.

### Validation errors

Errors found during validation (before any backend call) are reported as `failed <name>: <reason>` lines, where `<name>` falls back to the source-path stem (e.g. `failed deployment.yaml: <reason>`) if the manifest's name could not be resolved.

### `--wait` timeout

`--wait` adopts the same timeout convention used by `styrminctl deployments create --wait` — when that timeout elapses without reaching a terminal state, `failed <name>: wait timeout` is emitted and the deployment is counted as `failed` in the summary.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | every manifest was created or updated successfully (`failed = 0`) |
| `1` | any of: at least one manifest failed; required value unresolved; `--name` combined with batch input; no manifests found in input; YAML parse error; manifest validation error before processing |

A non-zero exit code is the contract for CI integration. Pipelines should not need to parse output to detect failure.

## Edge-case behaviour

| Situation | Behaviour |
|---|---|
| `-f <dir>` and the directory contains no `.yaml`/`.yml` files | exit `1` with `no manifests found in <dir>` |
| `-f <file>` where the file does not exist | exit `1` with `file not found: <path>` |
| Multi-doc YAML where one document is invalid | continue processing other documents; the invalid one is reported as `failed` |
| `--name` passed with more than one manifest | exit `1` with `--name cannot be combined with multiple manifests`; no manifests are processed |
| Network failure during a single manifest's create/update | report `failed <name>: <error>`; continue with remaining manifests |
| User Ctrl-C mid-batch | propagate; remaining manifests are not processed; exit code is whatever the signal handler installs (out of scope to formalise in v1) |

## Help text

`styrminctl deployments apply --help` MUST include:
- a one-line summary;
- a brief mention of the `apiVersion: styrmin/v1` / `kind: Deployment` schema and a link to the manifest-schema contract;
- the override precedence rule;
- an example invocation;
- a note that `config` and `parameters` are **fully replaced**, not merged.

## Out of scope (CLI v1)

- `--dry-run`
- `--output json`
- Recursive directory traversal (`-R`)
- Stdin input
- `--allow-driver-change`
- Deletion (`apply` does not delete deployments missing from a directory)
