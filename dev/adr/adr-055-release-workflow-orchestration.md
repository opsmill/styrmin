# ADR-055: Release workflow orchestration — split orchestrator/reusable jobs, static concurrency group with `cancel-in-progress: false`

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/003-automated-release/research.md (R8, R9)

## Context

The automated daily release pipeline has to do several things in sequence:

1. Detect whether new commits have landed on `develop` since the last release tag (skip if none).
2. Bump the version in `pyproject.toml` and the Helm `Chart.yaml` files.
3. Commit and tag the bump.
4. Create a GitHub Release with auto-generated notes.
5. Build, push, and sign multi-arch Docker images.
6. Publish updated Helm charts.

Two orthogonal architectural questions:

**Workflow shape** — one monolithic workflow that does all six steps, or a split between an orchestrator and reusable child workflows?

**Concurrency safety** — what happens if a second release fires while the first is still running? Cancelling mid-release could leave half-pushed images, dangling tags, or a chart pushed without its matching image.

A precedent already existed: `publish-helm-chart.yml` was a reusable workflow that `workflow_call`-d from elsewhere. The release pipeline could either extend that pattern or collapse everything into one file.

## Decision

### Workflow shape — orchestrator + reusable child workflows

The release pipeline is **two workflows**:

- **`release.yml`** (orchestrator): owns version bumping, commit, tag, GitHub Release creation, and dispatches the build/publish work to reusable children.
- **`docker-publish.yml`** (reusable via `workflow_call`): handles the multi-arch build → push → sign sequence. Independently triggerable via `workflow_dispatch` for manual retries.
- **`publish-helm-chart.yml`** (existing, unchanged): called twice from the orchestrator (once for agent chart, once for styrmin chart).

The orchestrator passes the version, tags, and other context as `workflow_call` inputs. Child workflows have no knowledge of the orchestrator — they take inputs and act.

### Concurrency safety — static group, never cancel in-flight

The orchestrator declares:

```yaml
concurrency:
  group: automated-release
  cancel-in-progress: false
```

- The group name is **static** (`automated-release`), not derived from the ref or commit SHA. This ensures only **one** release runs at a time across the whole project, regardless of trigger source (scheduled daily, manual dispatch, push to `develop`).
- `cancel-in-progress: false` means a second trigger **queues** behind the running release instead of cancelling it. If a third trigger arrives while the second is queued, the third **replaces** the second (the queue depth is one).

Reusable child workflows do not declare their own concurrency — they run as nested jobs within the orchestrator's concurrency group.

## Consequences

- **Independent retry** is possible: if Docker publishing fails mid-release, an operator can `workflow_dispatch` `docker-publish.yml` directly with the same inputs, without re-running the version bump and tag creation. (FR-010 / FR-015.)
- **Separation of concerns**: release logic (version bump, tag, GitHub Release) lives in `release.yml`; build logic (docker buildx, cosign signing, manifest merge) lives in `docker-publish.yml`. Each can evolve without touching the other.
- **Consistency with `publish-helm-chart.yml`**: the existing reusable-workflow pattern is the same shape; reviewers reading either file see the same idiom.
- **In-flight release safety**: a daily-schedule trigger that fires while a manual release is still running queues instead of cancelling. No half-pushed images, no dangling tags from a killed signing job.
- **Queue depth of one**: if multiple triggers stack while the head is running, the latest replaces older queued ones. This is the right behaviour — only the most recent commit-set is worth releasing; intermediate triggers are stale.
- **Operational cost**: the split adds one file to the repo and requires understanding `workflow_call` semantics. The complexity payoff is the retry pathway and clean separation; for a more frequently-run workflow this would not be worth it.
- **What `cancel-in-progress: false` does NOT protect against**: a `develop` push during version-bump-and-tag still produces a queued release that targets the post-push state. That is the desired behaviour — the next release ships the next set of commits.

## Alternatives Considered

- **Single monolithic workflow**: rejected. Harder to retry individual steps (a failed docker publish forces re-running the version bump, which would refuse on the regression guard). Also violates the existing `publish-helm-chart.yml` pattern.
- **Three or more workflows** (separate version-bump, separate release-creation, separate orchestration of the others): rejected. Version bump, tag creation, and GitHub Release are tightly coupled and have no independent reuse case. Splitting them would be ceremony.
- **`cancel-in-progress: true`**: rejected as dangerous. Cancelling a release mid-flight can leave half-pushed images at the registry, partially-created tags, or an image pushed without a matching signature. The cost of waiting for the in-flight run to finish is small; the cost of cleaning up a corrupt release is large.
- **No concurrency control**: rejected. Could produce duplicate releases or race conditions on `git push origin v1.2.3` if two release runs happen to land on the same tag simultaneously.
- **Per-ref concurrency group** (e.g., `release-${{ github.ref }}`): rejected. The release pipeline only releases off `develop`, and even there only one release-in-flight is correct. A per-ref group would allow concurrent releases off different branches if that ever became possible — preferable to forbid that structurally.
