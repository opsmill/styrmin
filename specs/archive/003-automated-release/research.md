# Research: Automated Daily Release Pipeline

**Feature**: 003-automated-release | **Date**: 2026-04-03

## R1: Version Bumping Strategy

**Decision**: Use `sed` to read/write `pyproject.toml` version; `yq` for Helm `Chart.yaml` files

**Rationale**: `sed` is universally available on GitHub-hosted runners with zero install overhead. `yq` is already used in the existing `publish-helm-chart.yml` workflow, so it's a known dependency. Dedicated Python bump tools (`bump-my-version`, `bumpver`) add unnecessary complexity for a single patch increment.

**Alternatives considered**:
- `bump-my-version` Python package — requires pip install step, configuration file, overkill for patch-only bumps
- `yq` for pyproject.toml — `yq` handles TOML poorly; `sed` is more reliable for the simple `version = "x.y.z"` pattern
- Manual version editing — defeats the purpose of automation

## R2: GitHub Release Creation

**Decision**: Use `gh release create` CLI with `--generate-notes`

**Rationale**: `gh` is pre-installed on all GitHub-hosted runners, maintained by GitHub, requires no action version pinning or third-party audit. The `--generate-notes` flag produces the same auto-generated release notes as the GitHub UI (PR titles since the last tag).

**Alternatives considered**:
- `softprops/action-gh-release@v2` — useful when attaching binary artifacts, but adds a third-party dependency for no benefit here
- Custom release notes script — unnecessary; GitHub's auto-generated notes are sufficient per spec clarifications

## R3: New Commit Detection

**Decision**: Use `git rev-list --count` to count commits since last `v*` tag

**Rationale**: Simple, reliable, no external dependencies. Requires `fetch-depth: 0` on checkout.

```bash
LAST_TAG=$(git describe --tags --match "v*" --abbrev=0 2>/dev/null || echo "")
if [ -z "$LAST_TAG" ]; then
  COMMIT_COUNT=$(git rev-list --count HEAD)
else
  COMMIT_COUNT=$(git rev-list --count "${LAST_TAG}..HEAD")
fi
```

**Alternatives considered**:
- GitHub API to compare commits — adds API call latency and complexity
- `git log --oneline` with `wc -l` — less precise than `rev-list --count`

## R4: Version Regression Guard

**Decision**: Use `sort -V` (GNU coreutils version sort) to compare semver strings

**Rationale**: Available on all GitHub-hosted Linux runners. No external semver tool needed.

```bash
GREATER=$(printf '%s\n%s\n' "$LATEST_TAG" "$NEW_VERSION" | sort -V | tail -1)
if [ "$GREATER" != "$NEW_VERSION" ] || [ "$LATEST_TAG" = "$NEW_VERSION" ]; then
  echo "ERROR: version regression"
  exit 1
fi
```

**Alternatives considered**:
- `semver` npm package — requires Node.js install step
- Custom bash semver comparator — `sort -V` is simpler and handles the comparison natively

## R5: Docker Image Signing with Cosign

**Decision**: Keyless signing via `sigstore/cosign-installer@v4` with GitHub Actions OIDC identity

**Rationale**: Keyless signing eliminates key management overhead. GitHub Actions OIDC token provides verifiable identity. Signatures are automatically logged in Rekor public transparency log. `COSIGN_EXPERIMENTAL` is deprecated as of cosign 2.0 — keyless is now the default behavior.

**Key implementation details**:
- Requires `id-token: write` permission on the job
- Sign by digest (not tag) to prevent TOCTOU attacks: `cosign sign --yes image@sha256:...`
- `--yes` flag required in CI to suppress interactive prompts
- Rekor upload is on by default — no flag needed

**Verification command for consumers**:
```bash
cosign verify \
  --certificate-identity-regexp "https://github.com/opsmill/styrmin/.github/workflows/.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  IMAGE@DIGEST
```

**Alternatives considered**:
- Key-based signing — requires managing signing keys as secrets, rotation burden
- Notation (from Notary Project) — less mature GitHub Actions integration than cosign

## R6: Docker Build and Push

**Decision**: Use `docker/build-push-action@v7` with `docker/metadata-action@v6` and `docker/login-action@v4`

**Rationale**: Industry standard, well-maintained, supports BuildKit layer caching, multi-tag output, and integrates cleanly with cosign (exposes digest output).

**Tag strategy**:
- On version tag (`v*`): push version tag (e.g., `0.1.1`), git SHA, and `latest`
- On `develop` push: push `latest` and git SHA only (no version tag)
- On `workflow_dispatch`: push git SHA and branch-derived tag

**Alternatives considered**:
- Raw `docker build && docker push` — loses BuildKit caching, requires manual tag management
- `ko` builder — only for Go applications
- Kaniko — unnecessary complexity for standard Dockerfile builds

## R7: Pushing Version Bump Commits

**Decision**: Use `GITHUB_TOKEN` with `contents: write` permission; add `[skip ci]` to commit message

**Rationale**: `GITHUB_TOKEN` can push to non-protected branches and can push tags. Commits pushed by `GITHUB_TOKEN` do not trigger subsequent workflow runs (loop prevention by design). `[skip ci]` provides belt-and-suspenders protection.

**Important**: If `develop` has branch protection rules requiring PR reviews, a GitHub App token or PAT with bypass permissions will be needed instead. This should be verified during implementation.

**Alternatives considered**:
- Personal Access Token (PAT) — requires a human's token stored as a secret, audit concern
- GitHub App token — better than PAT but adds setup complexity; only needed if branch protection blocks GITHUB_TOKEN

## R8: Workflow Concurrency

**Decision**: Use `concurrency` with a static group name and `cancel-in-progress: false`

**Rationale**: A release workflow must never be killed mid-flight (could leave partial artifacts). Static group name ensures only one release runs at a time. Second triggers queue as pending; third triggers replace the pending one.

```yaml
concurrency:
  group: automated-release
  cancel-in-progress: false
```

**Alternatives considered**:
- `cancel-in-progress: true` — dangerous for release workflows, could leave half-pushed artifacts
- No concurrency control — could produce duplicate releases or race conditions on version bumps

## R9: Workflow Architecture (Single vs. Split)

**Decision**: Two workflows — `release.yml` (orchestrator) and `docker-publish.yml` (reusable)

**Rationale**: Splitting Docker publishing into its own reusable workflow (with `workflow_call`) enables:
1. Independent `workflow_dispatch` triggering for retries (FR-010, FR-015)
2. Separation of concerns — release logic vs. build logic
3. Consistency with the existing `publish-helm-chart.yml` pattern

The release workflow orchestrates: version bump → tag → GitHub Release → call `docker-publish.yml` → call `publish-helm-chart.yml` (×2 for agent + styrmin).

**Alternatives considered**:
- Single monolithic workflow — harder to retry individual steps, violates existing pattern
- Three+ workflows — over-split; version bump + tag + release are tightly coupled and belong together

## R10: Multi-Architecture Docker Build Strategy

**Decision**: Per-platform native builds via matrix strategy + manifest merge, NOT QEMU emulation

**Rationale**: QEMU emulation for arm64 on x86 runners is 5-10x slower than native builds. GitHub provides hosted ARM runners (`ubuntu-24.04-arm64`) that build arm64 images natively. Using a matrix strategy with `runs-on: ${{ matrix.runner }}` keeps the workflow DRY while ensuring each architecture builds on matching hardware.

**Build pipeline**:
1. `build` job (matrix: amd64 on `ubuntu-24.04`, arm64 on `ubuntu-24.04-arm64`) — each pushes image by digest only (no tags)
2. `merge` job — downloads per-arch digests, creates multi-arch manifest with `docker buildx imagetools create --tag <tags> <digest1> <digest2>`
3. `sign` job — cosign signs the manifest list digest (not per-arch)

**Key implementation details**:
- Per-arch images are pushed without tags (by digest) to avoid tag race conditions
- Digests are passed between jobs via GitHub Actions artifacts
- `docker/metadata-action` computes tags once in the merge job
- GHA cache is scoped per-platform to avoid cross-arch cache pollution: `scope=${{ matrix.platform }}`
- Cosign signs the manifest list digest, which covers both architectures

**Alternatives considered**:
- QEMU emulation (`docker/setup-qemu-action`) — works but 5-10x slower for arm64, unacceptable for daily releases within 15-min target (SC-002)
- Single multi-platform `docker buildx build --platform linux/amd64,linux/arm64` — requires QEMU for the non-native arch, same speed problem
- Separate workflows per-arch — unnecessary complexity; matrix strategy achieves the same with less YAML
