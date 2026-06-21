# Research: Declarative Deployment Management

**Feature**: 009-deployments-apply
**Phase**: 0 (Outline & Research)

This document records the design decisions made during planning. The PRD already resolved most major decisions; this file records the *why* in one place and notes the alternatives considered.

## D1. Where does upsert orchestration live: backend or SDK?

- **Decision**: Client-side, in `DeploymentResource.apply()` in the SDK.
- **Rationale**: A backend-side `apply` mutation would couple validation, lookup, and dispatch into one transaction-bearing endpoint, but the platform's existing surface already separates `deploy`, `update_deployment`, and `update_deployment_version`. Reusing those is simpler than introducing a new server-side compound mutation. It also keeps batch-level concerns (continue-on-error, summary, override resolution) entirely client-side, where they naturally belong, and makes the new code easy to test without spinning up a backend.
- **Alternatives considered**:
  - *Server-side apply mutation* — rejected: duplicates existing mutations, requires its own validation surface, complicates rollback semantics for partial failures.
  - *CLI does the orchestration directly, no SDK method* — rejected: any other tool consuming the SDK (other CLIs, scripts, future agents) would re-implement the same upsert logic.

## D2. How does the SDK look up a deployment by name?

- **Decision**: Add a new top-level GraphQL query `deployment(name: String!, environmentId: UUID!)` returning `Deployment | null`. Hide internal deployments, matching the existing `deployment(deploymentId)` query.
- **Rationale**: A natural-identity lookup is the minimum new surface needed for client-side upsert. `(name, environmentId)` is already a unique constraint at the database level, so the query is cheap and unambiguous. Returning `null` rather than erroring on not-found mirrors the existing `deployment(deploymentId)` convention and lets the SDK use a clean "if found → update, else → create" branch.
- **Alternatives considered**:
  - *List + filter client-side* — rejected: forces clients to fetch every deployment in the environment for a single lookup; pagination becomes a footgun.
  - *Filter argument on the existing `deployment(deploymentId)`* — rejected: the existing query is keyed on UUID; making `deploymentId` optional would invalidate type safety.
  - *Separate sentinel `lookup_deployment` query* — rejected: GraphQL convention is one well-named query per resource lookup; overloading via two argument shapes (ID *or* name) is noisier than a sibling field.

**Race-handling follow-up**: `apply()`'s lookup-then-create-or-update is not atomic. Two concurrent `apply` runs against the same `(name, environment)` can both observe "not found" and both call `deploy()`. The DB unique constraint will reject the second one. On a duplicate-name backend error, `apply()` MUST re-run the lookup once and switch to the update path if the deployment now exists; otherwise propagate the error verbatim. This keeps the user-facing message friendly under benign races without introducing locking.

## D3. Should config and parameters be merged or replaced?

- **Decision**: Full replacement. `apply` overwrites both `config` and `parameters` with whatever the manifest contains. Removing a key from the manifest removes it on the deployment.
- **Rationale**: The whole reason to use declarative apply is "manifest is the source of truth". A merge semantics violates that — there is no way to delete a key without an extra deletion command, and the deployed config drifts from the file. Full replacement makes the contract obvious and predictable.
- **Alternatives considered**:
  - *Strategic merge* (kubernetes-style) — rejected: surprising for users new to apply, hard to explain in a CLI help string, requires knowing the structure of every config object.
  - *Opt-in `--merge` flag* — rejected: encourages unprincipled use of merge as a workaround for not knowing what is in the existing config; the right answer is "read the deployment, edit the manifest, re-apply".

## D4. How is override precedence resolved?

- **Decision**: For each of `name`, `version`, `environment`, `cluster`: CLI flag > environment variable (`STYRMIN_NAME` / `STYRMIN_VERSION` / `STYRMIN_ENVIRONMENT` / `STYRMIN_CLUSTER`) > manifest field.
- **Rationale**: This is the standard precedence for tooling that has to fit into CI pipelines (local dev sets the manifest, CI sets the env, an operator's flag overrides everything for ad-hoc work). It is composable: you do not have to know the env state to know what the flag will do — it always wins.
- **Alternatives considered**:
  - *Manifest > env > flag* — rejected: makes manifests the absolute source of truth and removes flag overrides as a useful concept (only "absent" fields can be overridden), defeating the CI-promotion use case in US3.

## D5. What should happen on driver mismatch during update?

- **Decision**: Fail the manifest with a clear actionable error. Do not modify the deployment. Continue to other manifests in the batch.
- **Rationale**: Driver changes are not in-place upgrades — switching drivers means switching helm charts, value templates, and components. The platform does not support it; supporting it via `apply` would silently delete-and-recreate, which violates the idempotency expectation and risks data loss.
- **Alternatives considered**:
  - *Auto-delete and recreate* — rejected: dangerous default; data-loss-risking implicit destructive behaviour.
  - *Allow with explicit `--allow-driver-change`* — deferred: out of scope for v1; if it becomes a real workflow it can be added without breaking existing manifests.

## D6. Is there a way to handle environment ambiguity (same env name on multiple clusters)?

- **Decision**: The `cluster` field in the manifest (or `--cluster` flag, or `STYRMIN_CLUSTER`) is a disambiguation hint, not part of the deployment identity. If the environment name resolves uniquely, `cluster` is optional. If it is ambiguous and no cluster has been provided, `apply` fails the manifest with a message that names the colliding clusters.
- **Rationale**: Mirrors how the existing `deployments create` command already handles environment+cluster resolution. Keeps single-cluster setups (the common case) friction-free while still being correct for multi-cluster teams.
- **Alternatives considered**:
  - *Always require cluster* — rejected: noisy in the common single-cluster case and inconsistent with `create`.
  - *Pick "first match" on ambiguity* — rejected: silent and order-dependent.

## D7. Default behaviour: fire-and-forget vs wait?

- **Decision**: Fire-and-forget by default; opt-in `--wait` to block until terminal state.
- **Rationale**: Matches the existing convention of `deployments create --wait` and `backups create --wait`. Most batches are long enough that synchronous waits would dominate latency and surprise users.
- **Alternatives considered**:
  - *Wait by default, opt-out* — rejected: inconsistent with existing platform commands; surprising in CI where batch sizes vary.

## D8. How are config/parameters values updated together with version?

- **Decision**: When both have changed, run `update_deployment` (config/parameters) first, then `update_deployment_version`. Sequential, not parallel.
- **Rationale**: The platform's instance-ID-based status reporting means the final reconciliation incorporates both changes. Running version-upgrade first risks the new version reconciling against the old config briefly. Running them in parallel would race against the same Deployment row.
- **Alternatives considered**:
  - *One compound mutation* — rejected: that mutation does not exist, see D1.
  - *Version-upgrade first* — rejected: brief reconciliation against stale config.

## D9. How is YAML parsed and validated?

- **Decision**: PyYAML's `safe_load_all()` for multi-document parsing. Pydantic model `DeploymentManifest` (with `model_config = ConfigDict(extra="forbid")`) for schema validation. Validation runs before any backend call.
- **Rationale**: PyYAML is the standard. `safe_load_all` handles `---`-separated documents natively. `extra="forbid"` is the strictest reasonable contract — typos in field names should fail loudly so users do not silently apply something they did not mean.
- **Alternatives considered**:
  - *ruamel.yaml* — rejected: heavier dep without need for round-trip preservation in v1.
  - *Manual parsing* — rejected: never write your own YAML parser.
  - *Allow extra fields with a warning* — rejected: silent typo paths are exactly what apply must avoid.

**Security note**: We use `yaml.safe_load_all` exclusively. We do **not** use `yaml.load_all` or `yaml.unsafe_load_all` — those allow arbitrary Python object construction and are RCE-prone. This is the standard precaution for any code that loads user-supplied YAML.

## D10. How does the CLI handle directory input?

- **Decision**: `-f <dir>` applies the directory's immediate `.yaml`/`.yml` files (non-recursive). Order is sorted ascending by filename so output is predictable across runs.
- **Rationale**: Predictable, simple, and matches `kubectl apply -f <dir>` semantics for v1. Recursive traversal is rarely the right default for deployment manifests (subdirectories often hold templates or examples).
- **Alternatives considered**:
  - *Recursive by default* — rejected: surprising; `templates/` and `examples/` directories would be picked up.
  - *Recursive with `-R` flag* — deferred: easy to add later without breaking existing usage.

## D11. What goes into the per-deployment status output?

- **Decision**: One line per deployment, in the order processed: `created <name>`, `updated <name>`, or `failed <name>: <reason>`. After all manifests, one summary line: `N created, M updated, K failed`.
- **Rationale**: Matches the PRD literally. Streaming the per-deployment line as each one finishes (rather than batching at the end) gives operators progress visibility on long batches.
- **Alternatives considered**:
  - *Structured JSON output mode* — deferred: a `--output json` flag is a reasonable v2; not in scope for v1.

## D12. PyYAML — direct or transitive dependency?

- **Decision**: Add `pyyaml` as a direct dep of the `cli/` package's `pyproject.toml`. It is already transitively present (Prefect → PyYAML), but pinning it directly in the consumer means we do not break if Prefect drops it.
- **Rationale**: The standard practice for "we consume PyYAML directly" is to depend on it directly. The constitution requires explicit discussion for new dependencies; this one is justified by the feature's core (it would not exist without YAML parsing) and is industry-standard.
- **Alternatives considered**:
  - *Rely on transitive* — rejected: brittle; transitive presence is not a contract.

**Placement scope**: PyYAML is a direct dep of **both** `python_sdk/pyproject.toml` and `cli/pyproject.toml`, because `DeploymentResource.apply_files()` parses YAML in the SDK so non-CLI tooling can call it directly. (If we ever extract a pure-orchestration `apply()` API that takes already-parsed dicts, the SDK dep could be dropped — but `apply_files()` is the natural API for non-CLI consumers.)

## D13. Is the `styrmin/v1` manifest format intended to be kubectl-compatible?

- **Decision**: No. The format is *Kubernetes-inspired* (apiVersion/kind/metadata/spec) but deliberately not kubectl-compatible in v1. There is no Styrmin CRD, no in-cluster operator, and no plan to feed these manifests to `kubectl`.
- **Rationale**: Borrowing the shape gives users a familiar mental model for free. Committing to full compatibility would lock us into kubectl's exact field semantics (label selectors, owner references, generation/revision) that are not relevant to Styrmin's deployment model.
- **Reconsideration trigger**: If a future Styrmin-in-cluster operator is introduced, the manifest format could evolve toward CRD compatibility at that time. Captured for record; no action required for v1.
