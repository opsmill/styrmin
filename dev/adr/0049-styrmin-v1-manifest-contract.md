# ADR-049: The `styrmin/v1` deployment manifest contract

**Status**: Accepted
**Date**: 2026-08-04
**Source**: specs/archive/009-deployments-apply/research.md (D3, D4, D6, D9, D10, D13)
**Related**: [ADR-048](0048-declarative-apply-client-side-orchestration.md) (who applies
these manifests), [ADR-018](0018-typed-update-deployment-input.md) (the
full-replacement input semantics the manifest inherits).

## Context

Declarative apply needs an on-disk input format. The format is a public contract
— users commit these files, template them in CI, and diff them in review — so
its semantics have to be obvious and its evolution constrained. Five questions
had to be settled before the first manifest shipped: how strict is parsing, what
does an update do to keys the manifest omits, how do CLI flags and environment
variables interact with file contents, is `cluster` part of a deployment's
identity, and does `apiVersion: styrmin/v1` promise anything to `kubectl`.

## Decision

### 1. Kubernetes-inspired shape, deliberately **not** kubectl-compatible

A manifest is `apiVersion: styrmin/v1`, `kind: Deployment`, `metadata.name`,
and a `spec` of `driver`, `version`, `environment`, optional `cluster`,
`config`, `parameters`. Multiple documents per file, `---`-separated.

Borrowing the shape gives users a familiar mental model for free. It commits us
to nothing else: there is no Styrmin CRD, no in-cluster manifest consumer, and
no intent to feed these files to `kubectl`. Full compatibility would bind us to
kubectl's field semantics — label selectors, owner references,
generation/revision — none of which map onto Styrmin's deployment model.

**Reconsideration trigger**: if a Styrmin in-cluster operator ever consumes
user-authored manifests, the format can evolve toward CRD compatibility then.

### 2. Strict parsing — `extra="forbid"`, `safe_load_all` only

`DeploymentManifest` is a Pydantic model with `model_config =
ConfigDict(extra="forbid")` at every level. An unknown key at the top level,
under `metadata`, or under `spec` is a validation error naming the key. Wrong
`apiVersion` or `kind` errors with the supported values listed. All validation
runs before any backend call.

A typo in a field name must fail loudly. The whole value of a declarative file
is that what it says is what you get; a silently-ignored `parmeters:` key is the
worst possible outcome.

Parsing uses `yaml.safe_load_all()` exclusively. `yaml.load_all` and
`yaml.unsafe_load_all` construct arbitrary Python objects and are RCE-prone —
they must never appear in any path that reads user-supplied YAML.

### 3. `config` and `parameters` are fully replaced, never merged

Apply overwrites both wholesale. Removing a key from the manifest removes it
from the deployment.

The manifest is the source of truth; merge semantics would break that — there
would be no way to delete a key without a second command, and the deployed
config would silently drift from the file. This matches the full-replacement
semantics `UpdateDeploymentInput` already has
([ADR-018](0018-typed-update-deployment-input.md)).

### 4. Override precedence: CLI flag > environment variable > manifest field

For each of `name`, `version`, `environment`, `cluster`: an explicit flag beats
`STYRMIN_NAME` / `STYRMIN_VERSION` / `STYRMIN_ENVIRONMENT` / `STYRMIN_CLUSTER`,
which beats the manifest.

This is the standard ladder for tooling that has to sit in a pipeline: the
manifest is the committed default, CI supplies the environment, an operator's
flag wins for ad-hoc work. It is composable — you never need to know the
environment's state to predict what a flag will do.

If a required field (`name`, `driver`, `version`, `environment`) resolves from
no source, the loader raises `MissingRequiredFieldError` **before** any backend
call. `--name` combined with multiple manifests is rejected outright
(`BatchNameConflictError`) rather than applied to all of them.

### 5. `cluster` is a disambiguation hint, not part of identity

Deployment identity is `(name, environment)`. `cluster` — from the manifest,
`--cluster`, or `STYRMIN_CLUSTER` — only resolves *which* environment is meant
when the environment name is not unique. If the name resolves uniquely,
`cluster` is optional. If it is ambiguous and no cluster was given, the manifest
fails with a message naming the colliding clusters; apply never picks the first
match.

This keeps the single-cluster case (today's platform scope, per
[ADR-039](0039-single-cluster-platform-scope.md)) friction-free while staying
correct if that changes.

### 6. Directory input is non-recursive, sorted

`-f <dir>` applies the directory's immediate `.yaml` / `.yml` files, sorted
ascending by filename so batch order is stable across runs. Recursion is not the
right default — `templates/` and `examples/` subdirectories would get picked up.
A `-R` flag can be added later without breaking existing usage.

## Consequences

- **Adding a field is cheap; changing one is a version bump.** New optional
  `spec` keys are additive. Renaming or re-typing an existing key breaks every
  committed manifest and needs `styrmin/v2`.
- **`extra="forbid"` makes forward-compatibility asymmetric.** An *older* CLI
  reading a manifest that uses a *newer* optional field fails rather than
  ignoring it. That is the intended trade-off — silent partial application is
  worse than a clear error — but it means new fields require a CLI upgrade, not
  just a schema bump.
- **Full replacement means "read, edit, re-apply".** There is no supported way
  to change one key of a deployment's config from a partial manifest. Operators
  who want that should fetch the current config first.
- **Apply is not a delete operation.** A deployment missing from a directory is
  not pruned. `kubectl apply --prune` has no equivalent and none is planned.
- **Manifest validation is entirely client-side.** The backend never sees a
  manifest — only the resolved mutation inputs — so manifest-level errors cannot
  be centrally enforced for non-SDK clients.

## Alternatives Considered

- **kubectl-compatible manifests.** Rejected: locks us into field semantics
  irrelevant to Styrmin for a compatibility nobody asked for.
- **Strategic merge (Kubernetes-style) for `config`.** Rejected: surprising for
  newcomers, impossible to explain in a CLI help string, and it requires knowing
  the structure of every config object to predict the result.
- **An opt-in `--merge` flag.** Rejected: it becomes the workaround for not
  knowing what is already in the config, when the right answer is to read the
  deployment and edit the manifest.
- **Allowing extra fields with a warning.** Rejected: warnings get scrolled
  past in CI logs; a typo would apply something the author did not intend.
- **Manifest > env > flag precedence.** Rejected: makes the file absolutely
  authoritative and reduces flags to filling in blanks, defeating the
  CI-promotion workflow.
- **Always requiring `cluster`.** Rejected: noisy in the common single-cluster
  case and inconsistent with `deployments create`.
- **Recursive directory traversal by default.** Rejected: silently picks up
  templates and examples.
