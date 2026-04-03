# Tasks: Automated Daily Release Pipeline

**Input**: Design documents from `/specs/003-automated-release/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: CI/CD workflows are validated via `workflow_dispatch` manual triggers and dry-run mode as described in quickstart.md (satisfies Constitution V — no application code to unit test).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Workflow files**: `.github/workflows/`
- **Helm charts**: `helm/styrmin/Chart.yaml`, `helm/agent/Chart.yaml`
- **Version source**: `pyproject.toml`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify existing infrastructure and ensure prerequisites are in place

- [ ] T001 Verify existing `publish-helm-chart.yml` supports `workflow_call` trigger in `.github/workflows/publish-helm-chart.yml` — confirm it accepts `chart`, `publish`, and `branch` inputs; add `workflow_call` trigger if missing
- [ ] T002 Verify Harbor credentials (`HARBOR_USERNAME`, `HARBOR_PASSWORD`, `HARBOR_HOST`) are referenced correctly — check existing workflow for secret/variable naming conventions

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Create the Docker publishing workflow with multi-arch support (amd64 + arm64) — used by both US1 (as called workflow) and US2 (standalone)

**⚠️ CRITICAL**: The `docker-publish.yml` workflow must exist before the release orchestrator can call it

- [ ] T003 Create Docker publish workflow file `.github/workflows/docker-publish.yml` with workflow skeleton: `name`, `on` (workflow_dispatch, workflow_call, push to develop), `permissions` (contents: read, id-token: write, packages: write), and concurrency settings
- [ ] T004 Add `workflow_dispatch` inputs (`tag`: string required, `push`: boolean default false) and `workflow_call` inputs (same signature) to `.github/workflows/docker-publish.yml`
- [ ] T005 Add `build` job with matrix strategy to `.github/workflows/docker-publish.yml` — matrix includes `{platform: linux/amd64, runner: ubuntu-24.04}` and `{platform: linux/arm64, runner: ubuntu-24.04-arm64}`, using `runs-on: ${{ matrix.runner }}`; steps: checkout at specified ref, setup Docker Buildx (`docker/setup-buildx-action@v4`), login to Harbor (`docker/login-action@v4`) using `secrets.HARBOR_USERNAME`, `secrets.HARBOR_PASSWORD`, `vars.HARBOR_HOST`
- [ ] T006 Add per-arch build-and-push step to `build` job in `.github/workflows/docker-publish.yml` — use `docker/build-push-action@v7` with `platforms: ${{ matrix.platform }}`, context `.`, file `docker/Dockerfile`, push by digest only (no tags), GHA cache scoped by platform (`cache-from: type=gha,scope=${{ matrix.platform }}`, `cache-to: type=gha,scope=${{ matrix.platform }},mode=max`), export digest to file and upload as GitHub Actions artifact
- [ ] T007 Add `merge` job (depends on `build`) to `.github/workflows/docker-publish.yml` — runs on `ubuntu-24.04`, downloads digest artifacts, login to Harbor, compute Docker metadata tags (`docker/metadata-action@v6`) with tag rules: `type=semver,pattern={{version}}` for v* tags, `type=sha` always, `type=raw,value=latest` on develop or v* tag; merge per-arch digests into multi-arch manifest via `docker buildx imagetools create --tag <tags> <digests>`, output manifest digest
- [ ] T008 Add `sign` job (depends on `merge`) to `.github/workflows/docker-publish.yml` — runs on `ubuntu-24.04`, install cosign (`sigstore/cosign-installer@v4`), sign the merged manifest digest (`cosign sign --yes ${HARBOR_HOST}/opsmill/styrmin@${MANIFEST_DIGEST}`), requires `id-token: write` permission

**Checkpoint**: `docker-publish.yml` is complete — builds amd64 (ubuntu-24.04) and arm64 (ubuntu-24.04-arm64) natively, merges into multi-arch manifest, signs manifest. Triggerable via `workflow_dispatch` independently.

---

## Phase 3: User Story 1 — Daily Automated Patch Release (Priority: P1) 🎯 MVP

**Goal**: Automatically create a new patch release on a daily schedule when there are new commits on `develop`, including version bumping, tagging, and GitHub Release creation.

**Independent Test**: Trigger via `workflow_dispatch` (with `dry_run: true`) and verify: version is computed correctly, commit count logic works, version regression guard catches bad versions. Then trigger without dry_run and verify tag + GitHub Release are created.

### Implementation for User Story 1

- [ ] T009 [US1] Create release workflow file `.github/workflows/release.yml` with skeleton: `name: Release`, `on` (schedule cron `0 0 * * *`, workflow_dispatch with `dry_run` boolean input), `concurrency` (group: `automated-release`, cancel-in-progress: false), `permissions` (contents: write, actions: write), `runs-on: ubuntu-24.04` for all jobs
- [ ] T010 [US1] Add `check-changes` job to `.github/workflows/release.yml` — checkout with `fetch-depth: 0`, detect last `v*` tag via `git describe --tags --match "v*" --abbrev=0`, count commits since last tag via `git rev-list --count`, output `has_changes`, `current_version`, `new_version`, `last_tag`
- [ ] T011 [US1] Add version reading and patch increment logic to `check-changes` job in `.github/workflows/release.yml` — read version from `pyproject.toml` with `sed`, parse MAJOR.MINOR.PATCH, increment PATCH, set `new_version` output
- [ ] T012 [US1] Add version regression guard to `check-changes` job in `.github/workflows/release.yml` — compare `new_version` against latest tag using `sort -V`, fail with explicit error if regression detected (FR-016)
- [ ] T013 [US1] Add `create-release` job to `.github/workflows/release.yml` — runs on `ubuntu-24.04`, depends on `check-changes`, conditional on `has_changes == 'true'`, checkout develop, configure git user as `github-actions[bot]`
- [ ] T014 [US1] Add version file updates to `create-release` job in `.github/workflows/release.yml` — update `pyproject.toml` version with `sed`, update `helm/styrmin/Chart.yaml` version + appVersion with `yq`, update `helm/agent/Chart.yaml` version with `yq`
- [ ] T015 [US1] Add commit, tag, and push steps to `create-release` job in `.github/workflows/release.yml` — commit with `[skip ci]` message, create tag `v{new_version}`, push commit to develop, push tag, output `tag`
- [ ] T016 [US1] Add GitHub Release creation step to `create-release` job in `.github/workflows/release.yml` — use `gh release create` with `--generate-notes` and `--target develop`, pass tag from output (FR-014)
- [ ] T017 [US1] Add dry_run support to `.github/workflows/release.yml` — when `inputs.dry_run` is true, skip push/tag/release steps but still compute and log what would happen

**Checkpoint**: User Story 1 is complete — the release workflow can detect changes, bump versions, create tags, and publish GitHub Releases. Testable via `workflow_dispatch`.

---

## Phase 4: User Story 2 — Automated Docker Image Publishing (Priority: P1)

**Goal**: Automatically build, push, and sign Docker images when a version tag is created or when code is pushed to develop.

**Independent Test**: Push a version tag and verify Docker image appears in Harbor with correct tags (version, SHA, latest). Verify cosign signature via `cosign verify`.

### Implementation for User Story 2

- [ ] T018 [US2] Add `publish-docker` job to `.github/workflows/release.yml` — depends on `create-release`, calls `./.github/workflows/docker-publish.yml` via `uses` with `tag` and `push: true` inputs, `secrets: inherit`

**Checkpoint**: User Story 2 is complete — Docker images are automatically built, pushed, and signed as part of the release pipeline. Also independently triggerable via `workflow_dispatch` on `docker-publish.yml`.

---

## Phase 5: User Story 3 — Automated Helm Chart Publishing (Priority: P1)

**Goal**: Automatically publish both styrmin and agent Helm charts to the OCI registry with version-aligned chart versions.

**Independent Test**: Push a version tag and verify both `styrmin` and `agent` charts appear in the OCI registry with the correct version. Verify via `helm show chart oci://<HARBOR_HOST>/opsmill/chart/styrmin --version <version>`.

### Implementation for User Story 3

- [ ] T019 [US3] Add `publish-helm-agent` job to `.github/workflows/release.yml` — depends on `create-release`, calls `./.github/workflows/publish-helm-chart.yml` with `chart: agent`, `publish: true`, `branch: <tag>`, `secrets: inherit`
- [ ] T020 [US3] Add `publish-helm-styrmin` job to `.github/workflows/release.yml` — depends on `create-release` AND `publish-helm-agent` (agent must be published first due to OCI dependency), calls `./.github/workflows/publish-helm-chart.yml` with `chart: styrmin`, `publish: true`, `branch: <tag>`, `secrets: inherit`

**Checkpoint**: User Story 3 is complete — both Helm charts are published in the correct order as part of the release pipeline.

---

## Phase 6: User Story 4 — Manual Major/Minor Version Bumps (Priority: P2)

**Goal**: Ensure human-set major/minor versions in `pyproject.toml` are respected and subsequent automated releases increment from the new base.

**Independent Test**: Manually set version to `0.2.0` in `pyproject.toml`, commit to `develop`, trigger release workflow — verify next release is `v0.2.1`.

### Implementation for User Story 4

- [ ] T021 [US4] Verify version reading logic in `check-changes` job (`.github/workflows/release.yml`) reads from `pyproject.toml` as source of truth — ensure manual major/minor bumps are picked up correctly (no hardcoded base version)
- [ ] T022 [US4] Verify version regression guard in `check-changes` job (`.github/workflows/release.yml`) handles major/minor bump scenarios — e.g., manual set to `0.2.0` when last tag is `v0.1.5` should pass, manual set to `0.1.0` when last tag is `v0.1.5` should fail

**Checkpoint**: User Story 4 is complete — manual version control works seamlessly with automated patch releases.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Finalize release status handling and ensure robustness

- [ ] T023 Add `finalize` job to `.github/workflows/release.yml` — depends on all publish jobs, runs `if: always()`, marks GitHub Release as draft if any publish job failed (`gh release edit --draft`), ensures release is published if all succeeded (FR-015)
- [ ] T024 Add dry_run guards to publish job calls in `.github/workflows/release.yml` — conditionally skip `publish-docker`, `publish-helm-agent`, and `publish-helm-styrmin` jobs when `inputs.dry_run` is true
- [ ] T025 Validate `docker-publish.yml` tag matrix against contract in `specs/003-automated-release/contracts/docker-publish.yml` — verify v* tag push produces version+SHA+latest, develop push produces SHA+latest, workflow_dispatch produces SHA only
- [ ] T026 Run quickstart.md validation — manually trigger full release via `workflow_dispatch` and verify all steps match the documented flow in `specs/003-automated-release/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup — `docker-publish.yml` BLOCKS User Story 2
- **User Story 1 (Phase 3)**: Depends on Setup — can start in parallel with Phase 2 (release.yml doesn't need docker-publish.yml to exist for initial development)
- **User Story 2 (Phase 4)**: Depends on Phase 2 (docker-publish.yml) and Phase 3 (release.yml create-release job)
- **User Story 3 (Phase 5)**: Depends on Phase 1 (publish-helm-chart.yml verification) and Phase 3 (release.yml create-release job)
- **User Story 4 (Phase 6)**: Depends on Phase 3 (version logic in check-changes job)
- **Polish (Phase 7)**: Depends on all story phases being complete

### User Story Dependencies

- **User Story 1 (P1)**: Independent — core release orchestration
- **User Story 2 (P1)**: Depends on US1 (needs `create-release` job output) + Foundational (needs `docker-publish.yml`)
- **User Story 3 (P1)**: Depends on US1 (needs `create-release` job output) + Setup (needs verified `publish-helm-chart.yml`)
- **User Story 4 (P2)**: Depends on US1 (validates version logic already built)

### Within Each User Story

- Workflow skeleton before job logic
- Job inputs/outputs before step implementation
- Core logic before edge cases

### Parallel Opportunities

- Phase 1 (T001, T002) can run in parallel
- Phase 2 tasks are sequential (T003 → T004 → T005 → T006 → T007 → T008) as they build on the same file
- Phase 3 tasks T009-T012 build the `check-changes` job sequentially; T013-T017 build the `create-release` job sequentially
- Phase 3 (US1) and Phase 2 (Foundational) can proceed in parallel — they edit different files
- Phase 4 (US2) and Phase 5 (US3) can proceed in parallel after US1 — they add independent jobs to `release.yml`
- Phase 7 tasks T023-T026 can run in parallel

---

## Parallel Example: Phase 2 + Phase 3

```bash
# These can run in parallel (different files):
Agent A: T003-T008 — Build docker-publish.yml
Agent B: T009-T017 — Build release.yml (US1)

# Then sequentially (all modify release.yml):
T018 — Add publish-docker job call (US2)
T019-T020 — Add publish-helm jobs (US3)
T023-T024 — Add finalize + dry_run guards (Phase 7)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Verify existing infrastructure (T001-T002)
2. Complete Phase 3: Build release.yml with version bump + tag + GitHub Release (T009-T017)
3. **STOP and VALIDATE**: Trigger via `workflow_dispatch` with `dry_run: true`
4. The release workflow can create versioned releases — Docker/Helm publishing added next

### Incremental Delivery

1. Setup + US1 → Version bumping and GitHub Releases work → Validate
2. Add Foundational (docker-publish.yml) + US2 → Docker images auto-published → Validate
3. Add US3 → Helm charts auto-published → Validate
4. Add US4 → Manual version control verified → Validate
5. Add Polish → Failure handling, dry_run, final validation → Done

### Parallel Team Strategy

With two developers:

1. Both verify Setup (Phase 1) together
2. Developer A: Phase 3 (release.yml — US1) in parallel with Developer B: Phase 2 (docker-publish.yml)
3. Once both done: Developer A adds US2+US3 jobs, Developer B handles US4+Polish

---

## Notes

- All new code is YAML workflow files under `.github/workflows/` — no application code changes
- `pyproject.toml` is the single source of truth for version
- Agent Helm chart MUST be published before styrmin chart (OCI dependency)
- `GITHUB_TOKEN` with `contents: write` is used for pushing — verify branch protection rules don't block this
- Commits by `GITHUB_TOKEN` do not trigger subsequent workflows (loop prevention built into GitHub Actions)
- `[skip ci]` in commit message provides belt-and-suspenders loop prevention
