# Feature Specification: Automated Daily Release Pipeline

**Feature Branch**: `003-automated-release`
**Created**: 2026-04-03
**Status**: Extracted
**Input**: User description: "Solve GH issues #28 and #29 — automated daily release pipeline with Docker image and Helm chart publishing, patch version auto-bump"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Daily Automated Patch Release (Priority: P1)

As a platform operator, I want Styrmin to automatically create a new patch release every day so that the latest changes on `develop` are always available as a versioned, deployable artifact without manual intervention.

**Why this priority**: This is the core requirement that enables all downstream automation (Docker image and Helm chart publishing). Without automated version bumping and tagging, the other stories have no trigger.

**Independent Test**: Can be fully tested by verifying that the scheduled workflow creates a new version tag (e.g., `v0.1.1`) from `develop`, increments the patch version in `pyproject.toml`, and pushes the tag to the repository.

**Acceptance Scenarios**:

1. **Given** the current version is `0.1.0` and there are new commits on `develop` since the last release, **When** the daily schedule triggers, **Then** a new tag `v0.1.1` is created and pushed, and `pyproject.toml` version is updated to `0.1.1`
2. **Given** there are no new commits on `develop` since the last release tag, **When** the daily schedule triggers, **Then** no new release is created (skip if no changes)
3. **Given** a human manually sets the version to `0.2.0` (minor bump), **When** the next daily schedule triggers with new commits, **Then** the patch version increments to `0.2.1`

---

### User Story 2 - Automated Docker Image Publishing (Priority: P1)

As a platform operator, I want the Docker image for Styrmin to be automatically built and pushed to the container registry whenever a new version tag is created, so that deployable images are always available for every release.

**Why this priority**: Docker images are the primary deployment artifact. Without automated image publishing, operators must build images manually, which is error-prone and blocks deployments. This directly addresses GH issue #28.

**Independent Test**: Can be fully tested by pushing a version tag (e.g., `v0.1.1`) and verifying that a Docker image appears in the registry with the correct version tag, SHA tag, and `latest` tag.

**Acceptance Scenarios**:

1. **Given** a new version tag `v0.1.1` is pushed, **When** the CI workflow runs, **Then** the Docker image is built from `docker/Dockerfile` and pushed to the registry with tags `0.1.1`, the git SHA, and `latest`
2. **Given** a push to `develop` branch (not a tag), **When** the CI workflow runs, **Then** the Docker image is built and pushed with only the `latest` tag and git SHA tag (no version tag)
3. **Given** the workflow is triggered manually via `workflow_dispatch`, **When** a user provides a branch or tag, **Then** the image is built and pushed with appropriate tags
4. **Given** the registry credentials are invalid or the push fails, **When** the workflow runs, **Then** the job fails with a clear error message indicating the authentication or push failure
5. **Given** a new version tag is pushed, **When** the Docker workflow runs, **Then** the resulting image manifest contains both `linux/amd64` and `linux/arm64` platforms, each built natively on architecture-matched runners

---

### User Story 3 - Automated Helm Chart Publishing (Priority: P1)

As a platform operator, I want the Helm charts to be automatically published to the OCI registry whenever a new version tag is created, so that the chart version stays aligned with the application version and is immediately available for deployments.

**Why this priority**: The Helm chart is the deployment mechanism for Kubernetes. Chart version alignment with the application version is critical for consistent deployments. This directly addresses GH issue #29.

**Independent Test**: Can be fully tested by pushing a version tag and verifying that both the `styrmin` and `agent` Helm charts appear in the OCI registry with the matching version.

**Acceptance Scenarios**:

1. **Given** a new version tag `v0.1.1` is pushed, **When** the release workflow runs, **Then** both `styrmin` and `agent` Helm charts are packaged and pushed to the OCI registry with version `0.1.1`
2. **Given** the existing `publish-helm-chart.yml` workflow, **When** the release workflow triggers chart publishing, **Then** it reuses the existing workflow (via `workflow_call`) rather than duplicating logic
3. **Given** the registry credentials are invalid, **When** the workflow runs, **Then** it fails with a clear error message

---

### User Story 4 - Manual Major/Minor Version Bumps (Priority: P2)

As a release manager, I want to manually control major and minor version bumps so that semantic versioning is respected and breaking changes or new features are explicitly versioned by humans.

**Why this priority**: Semantic versioning discipline requires human judgment for major/minor bumps. Automating only patch versions protects against unintentional breaking-change releases.

**Independent Test**: Can be fully tested by manually updating the version in `pyproject.toml` to a new minor/major version, committing to `develop`, and verifying the next automated release increments from that new base.

**Acceptance Scenarios**:

1. **Given** a human updates `pyproject.toml` version to `0.2.0` and merges to `develop`, **When** the next daily release runs, **Then** the release is `v0.2.1` (patch increment from the new base)
2. **Given** a human updates `pyproject.toml` version to `1.0.0`, **When** the next daily release runs with new commits, **Then** the release is `v1.0.1`

---

### Edge Cases

- What happens when the daily schedule runs but `develop` has no new commits since the last tag? The workflow skips release creation entirely.
- What happens when the Docker build fails? The workflow fails and no image or tag is pushed. The version tag is still created but marked as a failed release.
- What happens when Helm chart publishing succeeds but Docker image publishing fails (or vice versa)? Each publishing step is independent; partial failures are reported but do not roll back successful steps. The version tag is preserved and the GitHub Release is marked as a draft, allowing the failed publish step to be retried via `workflow_dispatch`.
- What happens when two daily runs overlap (e.g., a delayed run)? GitHub Actions concurrency controls prevent parallel execution of the same workflow.
- What happens when `pyproject.toml` version is lower than the latest existing git tag (version regression)? The workflow fails with an explicit error, preventing accidental overwrite of registry artifacts.
- What happens on the very first release when no `v*` tags exist yet? The workflow treats all commits on `develop` as new changes. The version in `pyproject.toml` is used as-is (no patch increment since there is no prior release to increment from), and the first tag (e.g., `v0.1.0`) is created.

## Clarifications

### Session 2026-04-03

- Q: Should the release workflow create a GitHub Release object (with auto-generated release notes) or only a git tag? → A: Create a GitHub Release with auto-generated release notes
- Q: If Docker/Helm publishing fails after the version tag is created, what should happen to the tag? → A: Keep the tag; mark the GitHub Release as failed (pre-release/draft) so it can be retried
- Q: How should the team be notified of release outcomes? → A: GitHub notifications only (default watchers mechanism)
- Q: What should happen if pyproject.toml version is lower than the latest existing git tag? → A: Fail the workflow with an error (version regression guard)
- Q: Should Docker images be signed (e.g., cosign) for supply chain provenance? → A: Yes, sign images with cosign as part of the release workflow
- Q: Which cosign signing method should be used? → A: Keyless signing via Sigstore (OIDC identity from GitHub Actions, logged in Rekor)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST automatically create a new patch release on a daily schedule (cron) when there are new commits on `develop` since the last release tag
- **FR-002**: System MUST increment only the patch version component (e.g., `0.1.0` → `0.1.1`) for automated releases
- **FR-003**: System MUST NOT create a release when there are no new commits since the last release tag
- **FR-004**: System MUST build the Docker image from `docker/Dockerfile` and push it to the container registry on version tag events
- **FR-005**: System MUST tag Docker images with: the version number (e.g., `0.1.1`), the git commit SHA, and `latest`
- **FR-006**: System MUST update the `latest` Docker image tag on pushes to `develop`
- **FR-007**: System MUST publish both `styrmin` and `agent` Helm charts to the OCI registry on version tag events
- **FR-008**: System MUST align Helm chart versions with the release version
- **FR-009**: System MUST reuse existing Harbor registry credentials (`HARBOR_USERNAME`, `HARBOR_PASSWORD`, `HARBOR_HOST`)
- **FR-010**: System MUST support `workflow_dispatch` for manual triggering of both Docker and Helm publishing workflows
- **FR-011**: System MUST reuse the existing `publish-helm-chart.yml` workflow via `workflow_call` for Helm chart publishing
- **FR-012**: System MUST update the version in `pyproject.toml` and Helm chart `Chart.yaml` files as part of the release process
- **FR-013**: System MUST allow humans to manually set major or minor versions by editing `pyproject.toml`; subsequent automated releases increment the patch from that base
- **FR-014**: System MUST create a GitHub Release object with auto-generated release notes for each version tag
- **FR-015**: System MUST mark the GitHub Release as a draft when any publishing step (Docker or Helm) fails, preserving the tag for retry via `workflow_dispatch`
- **FR-016**: System MUST fail the release workflow with a clear error if the computed next version would be lower than or equal to the latest existing git tag (version regression guard)
- **FR-017**: System MUST sign Docker images using cosign keyless signing (Sigstore/Fulcio with GitHub Actions OIDC identity) after pushing to the registry, with signatures logged in Rekor for transparency
- **FR-018**: System MUST build multi-architecture Docker images for linux/amd64 and linux/arm64, published as a single multi-arch manifest. ARM images MUST be built on native ARM runners (not QEMU emulation).

### Key Entities

- **Release**: A versioned snapshot of Styrmin, identified by a semantic version tag (e.g., `v0.1.1`), comprising a Docker image and Helm charts
- **Version**: A semantic version string (`MAJOR.MINOR.PATCH`) tracked in `pyproject.toml` and `Chart.yaml`
- **Docker Image**: A multi-architecture container image (linux/amd64 + linux/arm64) built from `docker/Dockerfile`, tagged and pushed to the Harbor registry as a unified manifest
- **Helm Chart**: The Kubernetes deployment package (both `styrmin` and `agent` charts), published to the Harbor OCI registry

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new patch release is automatically created every day when there are unreleased changes, without human intervention
- **SC-002**: Every release produces a Docker image available in the registry within 15 minutes of the daily schedule trigger
- **SC-003**: Every release produces Helm charts in the OCI registry with versions matching the release version
- **SC-004**: Zero manual steps are required for the daily patch release process end-to-end (from version bump to published artifacts)
- **SC-005**: Manual major/minor version bumps are respected — automated releases always increment from the current version in `pyproject.toml`
- **SC-006**: Failed releases produce clear, actionable error messages visible in the GitHub Actions workflow logs

## Out of Scope

- External notification integrations (Slack, email) — GitHub built-in notifications are sufficient

## Assumptions

- The Harbor registry credentials (`HARBOR_USERNAME`, `HARBOR_PASSWORD`, `HARBOR_HOST`) are already configured as GitHub repository secrets/variables
- The `docker/Dockerfile` is the canonical Dockerfile for the Styrmin production image
- The `develop` branch is the primary integration branch from which releases are cut
- The existing `publish-helm-chart.yml` workflow is functional and can be called via `workflow_call`
- GitHub Actions is the CI/CD platform (no other CI systems are involved)
- The daily schedule time is not critical — a reasonable default (e.g., midnight UTC) is acceptable
- Both `styrmin` and `agent` Helm charts should be versioned and published together as part of each release
- The `pyproject.toml` at the repository root is the single source of truth for the application version
- Helm chart versions in `Chart.yaml` files will be synchronized with the `pyproject.toml` version during the release process
- Release notifications rely on GitHub's built-in notification system (repository watchers, workflow failure alerts); no external notification integrations (Slack, email) are required
