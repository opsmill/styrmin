# Feature Specification: Declarative Deployment Management via YAML Manifests

**Feature Branch**: `009-deployments-apply`
**Created**: 2026-05-08
**Status**: Extracted
**Input**: PRD from [opsmill/styrmin#194 (comment 4403612642)](https://github.com/opsmill/styrmin/issues/194#issuecomment-4403612642) — "Declarative Deployment Management via YAML Manifests"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Apply a single manifest to create or update a deployment (Priority: P1)

A platform engineer authors a YAML file describing the desired state of a single deployment (driver, version, environment, optional cluster, config, parameters) and runs `styrminctl deployments apply -f deployment.yaml`. The command creates the deployment if it does not exist, or converges the existing deployment to the manifest's desired state if it does — all from a single command suitable for storing in version control.

**Why this priority**: This is the core declarative workflow that the entire feature exists to enable. Without it, none of the batching, override, or wait behaviours have value. A user who can apply a single manifest already has a viable MVP for git-driven deployments.

**Independent Test**: Author a manifest, run `apply`, and verify a deployment is created. Modify the manifest's config and re-run; verify the same deployment is updated (not duplicated). Modify only the version and re-run; verify the deployment's version is upgraded.

**Acceptance Scenarios**:

1. **Given** no deployment exists with the manifest's `(name, environment)` identity, **When** the engineer runs `apply -f deployment.yaml`, **Then** the system creates the deployment using the manifest's driver, version, config, and parameters, and prints `created <name>`.
2. **Given** a deployment already exists with the same `(name, environment)`, **When** the engineer re-runs `apply` with an updated `config`, **Then** the system updates the existing deployment (replacing config and parameters in full, not merging) and prints `updated <name>`.
3. **Given** a deployment already exists, **When** the manifest specifies a `version` different from the currently deployed version, **Then** the system upgrades the version after applying any config/parameter changes, and prints `updated <name>`.
4. **Given** a deployment already exists, **When** the manifest specifies a `driver` different from the existing deployment's driver, **Then** the system errors with a clear message (driver change requires delete-and-recreate) and does not modify the deployment.
5. **Given** the manifest is malformed (missing `apiVersion`, wrong `kind`, missing required fields, unknown fields), **When** the engineer runs `apply`, **Then** the system fails validation with a human-readable error before any backend call is made.

---

### User Story 2 - Apply a batch of manifests with continue-on-error and a clear summary (Priority: P2)

A platform engineer maintains a directory or multi-document YAML file describing many deployments, and runs `styrminctl deployments apply -f ./manifests/` (or `-f a.yaml -f b.yaml`, or a single multi-document file). The command processes every manifest, prints a status line per deployment as it goes, continues past individual failures, and ends with a summary so the engineer can see at a glance what happened across the whole batch.

**Why this priority**: Once the single-file flow works, real users immediately want to manage many deployments together — across services, across environments, across teams. The continue-on-error semantics and final summary are what make this useful in CI: a single typo cannot block an unrelated deployment, and a non-zero exit code on any failure lets pipelines react correctly.

**Independent Test**: Place three valid manifests and one invalid manifest (e.g., one with a driver mismatch against an existing deployment) in a directory; run `apply -f ./manifests/`. Verify the three valid ones are created/updated, the invalid one is reported as failed, the summary line reports `N created, M updated, K failed`, and the exit code is non-zero.

**Acceptance Scenarios**:

1. **Given** a directory containing several `.yaml`/`.yml` manifests, **When** the engineer runs `apply -f ./manifests/`, **Then** every manifest in the directory is processed and a per-deployment status line is printed in the order processed.
2. **Given** multiple `-f` flags pointing at distinct files, **When** the engineer runs `apply -f a.yaml -f b.yaml`, **Then** both files are processed.
3. **Given** a single file containing several YAML documents separated by `---`, **When** the engineer runs `apply -f combined.yaml`, **Then** each document is treated as an independent manifest.
4. **Given** a batch where one manifest fails (validation error, driver mismatch, ambiguous environment, network error from the backend), **When** the engineer runs `apply`, **Then** the system continues processing the remaining manifests, prints `failed <name>: <reason>` for the failure, and ends with a summary line of the form `N created, M updated, K failed`.
5. **Given** at least one manifest failed in a batch, **When** the command finishes, **Then** the process exits with a non-zero exit code suitable for CI failure detection.
6. **Given** more than one manifest is being applied, **When** the engineer also passes `--name`, **Then** the command errors before processing any manifest with a clear explanation that `--name` cannot be combined with batch input.

---

### User Story 3 - Override manifest fields from CLI flags and environment variables (Priority: P2)

A platform engineer runs the same set of manifests across multiple environments or release pipelines without editing the files. They override `version`, `environment`, or `cluster` (and optionally `name` for single-manifest invocations) using CLI flags or environment variables, with a clear and documented precedence order.

**Why this priority**: This is what makes the feature usable in real release pipelines — promoting the same manifests from staging to production, pinning everything to a release tag in CI, or disambiguating a target cluster without rewriting files. Without overrides, every environment requires its own copy of every manifest. With overrides, one manifest set serves many pipelines.

**Independent Test**: Author a manifest with `spec.version: "1.2.3"`. Run `apply --version 1.4.0` and verify the deployment is created/updated at `1.4.0`. Set `STYRMIN_VERSION=1.5.0` and run `apply` (no flag); verify it deploys at `1.5.0`. Set `STYRMIN_VERSION=1.5.0` and run `apply --version 1.6.0`; verify the flag wins and the deployment is at `1.6.0`.

**Acceptance Scenarios**:

1. **Given** a manifest with a `spec.version` value, **When** the engineer runs `apply --version <X>`, **Then** the deployment is created/updated at version `<X>`, regardless of the manifest value.
2. **Given** the environment variable `STYRMIN_VERSION` is set and no `--version` flag is passed, **When** the engineer runs `apply`, **Then** the deployment uses the environment variable's version, regardless of the manifest value.
3. **Given** both `STYRMIN_VERSION` and `--version` are set, **When** the engineer runs `apply`, **Then** the CLI flag wins.
4. **Given** the same precedence rules apply identically to `--environment` / `STYRMIN_ENVIRONMENT` and `--cluster` / `STYRMIN_CLUSTER`, **When** the engineer applies a batch with any of these flags, **Then** the flag value is applied to every manifest in the batch.
5. **Given** a manifest that omits `spec.cluster` and an environment whose name matches multiple clusters, **When** the engineer runs `apply` without `--cluster` or `STYRMIN_CLUSTER`, **Then** the command errors with a message indicating the ambiguity and how to resolve it.
6. **Given** required fields cannot be resolved from any of (CLI flag, environment variable, manifest), **When** the engineer runs `apply`, **Then** the command exits non-zero with a clear error before making any backend call.

---

### User Story 4 - Wait for deployments to reach a terminal state (Priority: P3)

A platform engineer using `apply` as a deployment step in CI wants the command to block until every affected deployment reaches its terminal state (`RUNNING` or failed) so the pipeline only continues when the cluster has actually converged. By default, `apply` returns as soon as create/update operations are submitted, matching the existing fire-and-forget pattern; with `--wait`, the command blocks.

**Why this priority**: The default fire-and-forget behaviour is correct for most workflows and matches the platform's existing pattern (`backups create --wait`, `deployments create --wait`). `--wait` is genuinely useful for CI pipelines that need synchronous deployment, but the value is realised only after the rest of the feature works — so this is the lowest-priority slice.

**Independent Test**: Apply a manifest without `--wait`; verify the command exits within a few seconds (immediately after submission). Apply the same manifest with `--wait`; verify the command does not exit until the deployment reaches `RUNNING` (or fails) and reports the terminal state.

**Acceptance Scenarios**:

1. **Given** the engineer runs `apply` without `--wait`, **When** create/update operations are submitted to the backend, **Then** the command returns promptly without polling for terminal state.
2. **Given** the engineer runs `apply --wait`, **When** the command finishes, **Then** every successfully-submitted deployment has reached `RUNNING` or a terminal failure state, and the failure state is reflected in the summary and exit code.

---

### User Story 5 - Look up a deployment by name and environment (Priority: P3)

Tooling built on top of the SDK needs to resolve deployments by their natural identity — `(name, environment)` — without first knowing the platform's internal IDs. This SDK capability is what `apply` itself uses to decide create-vs-update, but it is also valuable to other automation (status checks, ad-hoc tooling, external orchestrators).

**Why this priority**: This is a foundational lookup required by `apply` itself, and useful to any other consumer of the SDK. It's listed as P3 because it is small in scope (a single new query) and is naturally delivered as part of US1's slice — but it is called out as an independently testable capability so other tooling can rely on it.

**Independent Test**: Through the SDK (or an equivalent direct API call), look up a deployment by `(name, environment)` and verify it returns the matching deployment. Look up a non-existent name; verify the lookup returns "not found". Look up a deployment that is internal/system-managed; verify it is hidden from the lookup, matching the existing single-deployment-by-id query.

**Acceptance Scenarios**:

1. **Given** a deployment exists with `(name=X, environment=Y)`, **When** the SDK is asked to look it up by `(X, Y)`, **Then** the existing deployment is returned.
2. **Given** no deployment exists for `(X, Y)`, **When** the lookup runs, **Then** the lookup returns a "not found" result rather than an error.
3. **Given** a system-internal deployment exists for `(X, Y)`, **When** the lookup runs, **Then** the lookup hides it (matching the existing convention for the single-deployment-by-id query).

---

### Edge Cases

- **Empty input**: `-f` points at a directory containing no `.yaml`/`.yml` files, or a file containing no documents. The command must not silently succeed; it should exit with a clear error indicating that no manifests were found.
- **Mixed-validity directory**: Some manifests in a directory are valid and some are not. Validation runs per-manifest; valid ones proceed, invalid ones are reported and counted toward the failure summary.
- **Stdin / glob expansion**: Out of scope for this feature — only file paths and directory paths are accepted. Shell glob expansion (`*.yaml`) is naturally supported because the shell expands it before the command sees it.
- **Multi-document YAML with a single invalid document**: Other documents in the same file still process; the invalid one is reported and counted as a failure.
- **Concurrent `apply` from multiple operators**: Out of scope for v1. The command does not implement optimistic locking or conflict detection; behaviour under concurrent apply is whatever the underlying create/update backend semantics produce.
- **Very large batches (e.g., hundreds of manifests)**: The command processes manifests sequentially. Performance optimisation (parallelism, streaming) is not in scope for v1.
- **Partial config replacement attempts**: Users sometimes expect `apply` to merge `config` rather than replace it. The contract is **full replacement**; this must be documented in the spec and reflected in the help text so the behaviour is unsurprising.
- **Driver field omitted on update**: If `spec.driver` is omitted from the manifest, validation fails — `driver` is always required, even on subsequent updates, so that a manifest is always self-describing.

## Requirements *(mandatory)*

### Functional Requirements

#### Manifest format and validation

- **FR-001**: The system MUST accept YAML manifests with `apiVersion: styrmin/v1`, `kind: Deployment`, a `metadata` section, and a `spec` section.
- **FR-002**: The system MUST validate every manifest against a defined schema before making any backend call. Unknown top-level keys, unknown fields under `spec`, missing required fields, and incorrect `apiVersion`/`kind` values MUST cause validation to fail with a human-readable error that identifies the offending file and field.
- **FR-003**: The system MUST treat `metadata.name`, `spec.environment`, and `spec.cluster` as optional in the manifest, since each can be supplied via CLI flag or environment variable. `spec.driver` MUST be required.
- **FR-004**: The system MUST treat `spec.config` and `spec.parameters` as optional objects that default to empty when omitted.

#### Apply command — create-or-update orchestration

- **FR-005**: The system MUST identify a deployment by its `(name, environment)` pair after all overrides have been resolved.
- **FR-006**: When no deployment exists for the resolved `(name, environment)`, the system MUST create a new deployment using the manifest's driver, version, config, and parameters, and report `created <name>`.
- **FR-007**: When a deployment exists for the resolved `(name, environment)`, the system MUST update the deployment's config and parameters to match the manifest exactly (full replacement, not merge), and MUST upgrade the version when it differs from the currently deployed version. The system MUST report `updated <name>`.
- **FR-008**: When updating an existing deployment, if the manifest's `driver` differs from the existing deployment's driver, the system MUST fail that deployment with a clear error explaining that driver changes are not supported by `apply` and require delete-and-recreate.
- **FR-009**: When both config/parameters and version have changed, the system MUST apply the config/parameters change first, then perform the version upgrade, so that the final reconciliation incorporates all changes.
- **FR-010**: The system MUST resolve the target environment by name (and optional cluster name) before deciding create-vs-update. If the environment name matches multiple clusters and no cluster has been specified, the system MUST fail that deployment with a clear error indicating the ambiguity and how to resolve it.

#### Override precedence and required-value resolution

- **FR-011**: For each of `name`, `version`, `environment`, and `cluster`, the system MUST apply the precedence: CLI flag > environment variable > manifest field. The supported environment variables are `STYRMIN_NAME`, `STYRMIN_VERSION`, `STYRMIN_ENVIRONMENT`, and `STYRMIN_CLUSTER`.
- **FR-012**: When a CLI flag for `name`, `version`, `environment`, or `cluster` is provided in batch mode, the flag MUST apply to every manifest in the batch.
- **FR-013**: The system MUST refuse to combine `--name` with batch input (more than one manifest) and MUST fail with a clear error before processing any manifest.
- **FR-014**: The system MUST exit non-zero with a clear error before any backend call when a required value (`name`, `driver`, `version`, `environment`) cannot be resolved from any of (CLI flag, environment variable, manifest).

#### Batch input

- **FR-015**: The system MUST accept any combination of (a) a single `-f <file>`, (b) repeated `-f <file>` flags, and (c) a single `-f <directory>` whose immediate `.yaml` and `.yml` files (non-recursively) are all applied. (Recursion is out of scope for v1; if needed it should be requested explicitly.)
- **FR-016**: The system MUST treat YAML documents separated by `---` within a single file as independent manifests, each subject to validation and apply independently.
- **FR-017**: The system MUST continue processing remaining manifests after any individual manifest fails (validation error, driver mismatch, ambiguity error, backend error). One bad manifest MUST NOT block the rest of the batch.
- **FR-018**: The system MUST exit with a non-zero exit code if any manifest in the batch failed.

#### Output

- **FR-019**: The system MUST print exactly one status line per deployment as it is processed: `created <name>`, `updated <name>`, or `failed <name>: <reason>`.
- **FR-020**: After all manifests have been processed, the system MUST print a single summary line of the form `N created, M updated, K failed`.

#### Wait mode

- **FR-021**: By default, the system MUST return promptly after submitting create/update operations to the backend (fire-and-forget), matching the existing convention of other deployment commands.
- **FR-022**: When `--wait` is passed, the system MUST block until every successfully-submitted deployment has reached its terminal state (`RUNNING` or failed). Failures observed during waiting MUST be reflected in the summary and exit code.

#### Lookup capability

- **FR-023**: The platform MUST support looking up a single deployment by `(name, environment)` through its primary API, returning a "not found" result rather than an error when there is no match. The lookup MUST hide system-internal deployments, matching the existing convention for the lookup-by-id capability.

### Key Entities

- **Deployment Manifest**: A YAML document with `apiVersion: styrmin/v1`, `kind: Deployment`, a `metadata.name`, and a `spec` block (`driver`, `version`, `environment`, optional `cluster`, optional `config`, optional `parameters`). The manifest is the user's authoritative source of truth for one deployment's desired state.
- **Deployment**: A platform-managed deployment, identified by `(name, environment)`. Has a current driver, version, config, parameters, and runtime state.
- **Environment**: A named target that lives inside a cluster. Environment names are not globally unique — the same environment name can exist on multiple clusters — so `cluster` is the disambiguation hint when needed.
- **Cluster**: A Kubernetes cluster registered with the platform; hosts one or more environments.
- **Apply Result**: For each manifest, a per-deployment outcome of `created`, `updated`, or `failed (<reason>)`. Aggregated into the summary line and the exit code.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A platform engineer can create a new deployment from a single YAML file in one command and observe the resulting deployment converge to `RUNNING` (when `--wait` is used or via subsequent status check) without invoking any imperative `create`, `update`, or `update-version` command.
- **SC-002**: Re-running the same `apply` command with no manifest changes does not create a duplicate deployment and does not produce errors — the system converges to the same state every time (idempotent in observable behaviour).
- **SC-003**: A batch of N manifests in which K are invalid completes with exactly N - K successful per-deployment outcomes and exactly K failed outcomes; the summary line and exit code reflect the same counts.
- **SC-004**: Applying the same manifest set across two environments (e.g., staging and production) requires editing zero manifest files when `--environment` (or `STYRMIN_ENVIRONMENT`) is used.
- **SC-005**: Validation errors (malformed YAML, unknown fields, missing required fields, wrong `apiVersion`/`kind`) are surfaced before any backend call is made and identify the offending file and field clearly enough that the user can fix the manifest without consulting documentation.
- **SC-006**: A driver-change attempt on an existing deployment is reported as a failure with a clear, actionable error message and does not modify the deployment.
- **SC-007**: A CI pipeline running `apply -f ./manifests/` exits non-zero on any manifest failure, allowing the pipeline's failure-handling logic to engage automatically.
- **SC-008**: An external automation tool can resolve a deployment by `(name, environment)` through the platform's primary API in a single call, without pre-knowing internal IDs.

## Assumptions

- **Platform conventions in scope**: This feature builds on the existing platform conventions for environment/cluster resolution, deployment create/update operations, and instance-ID-based status reporting. No changes to those conventions are in scope.
- **Identity stability**: The canonical identity of a deployment is `(name, environment)`. The cluster is a disambiguation hint, not part of the identity, consistent with how the existing `create` command already resolves environment+cluster.
- **Full replacement of config and parameters**: `apply` replaces `config` and `parameters` wholesale rather than merging. Users who want to remove a config key remove it from the manifest. This trade-off prioritises predictability and the manifest-as-source-of-truth contract over convenience for partial updates.
- **Out of scope for v1**: dry-run mode, diff output, declarative deletion (`apply` will not delete deployments missing from a directory), other `kind:` values (only `Deployment`), server-side apply (all upsert orchestration is client-side), and manifest export/generation from existing deployments.
- **Performance**: Batches are processed sequentially. Parallel apply, streaming output, and very-large-batch optimisation are out of scope for v1.
- **Concurrency**: No optimistic locking or conflict detection between concurrent `apply` runs is in scope; behaviour under concurrent apply is determined by the underlying backend's create/update semantics.
- **Recursive directory traversal**: `-f <dir>` applies the directory's immediate `.yaml`/`.yml` files only. Recursive traversal is out of scope for v1.
