# Data Model: Automated Daily Release Pipeline

**Feature**: 003-automated-release | **Date**: 2026-04-03

> This feature has no database entities. The "data model" describes the version artifacts, their relationships, and the state transitions managed by the CI/CD pipeline.

## Entities

### Version

The semantic version string that drives all release artifacts.

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| major | int | `pyproject.toml` | Manually set by humans |
| minor | int | `pyproject.toml` | Manually set by humans |
| patch | int | `pyproject.toml` | Auto-incremented by release workflow |

**Source of truth**: `pyproject.toml` → `project.version` field

**Synchronized copies** (updated at release time):
- `helm/styrmin/Chart.yaml` → `version` and `appVersion`
- `helm/agent/Chart.yaml` → `version`
- Git tag → `v{major}.{minor}.{patch}`

**Validation rules**:
- Must be valid semver (`MAJOR.MINOR.PATCH`, all non-negative integers)
- Must be strictly greater than the latest existing `v*` git tag (regression guard)

### Release

A versioned snapshot created by the release workflow.

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| version | string | Computed from Version entity | e.g., `v0.1.1` |
| tag | git tag | Created by workflow | Points to version bump commit on `develop` |
| github_release | GitHub Release | Created by `gh release create` | Auto-generated notes |
| status | enum | GitHub Release state | `published` or `draft` (on failure) |

**State transitions**:

```text
[no release] → [tag created] → [GitHub Release created (draft)]
  → [Docker published] → [Helm published] → [Release published]

On failure at any publish step:
  → [GitHub Release remains draft/pre-release for retry]
```

### Docker Image

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| registry | string | `vars.HARBOR_HOST` | Harbor OCI registry |
| repository | string | `opsmill/styrmin` | Fixed path |
| platforms | list[string] | Build matrix | `[linux/amd64, linux/arm64]` |
| tags | list[string] | Computed | `[version, git-sha, latest]` |
| manifest_digest | string | Merge job output | `sha256:...` (multi-arch manifest list) |
| per_arch_digests | map[string, string] | Build job outputs | `{amd64: sha256:..., arm64: sha256:...}` |
| signature | cosign | Sigstore/Rekor | Keyless, signed on manifest_digest |

**Tag rules**:
- On version tag push: `{version}`, `{git-sha}`, `latest`
- On `develop` push: `{git-sha}`, `latest`
- On `workflow_dispatch`: `{git-sha}`

### Helm Chart (×2: styrmin, agent)

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| name | string | `Chart.yaml` | `styrmin` or `styrmin-agent` |
| version | string | `Chart.yaml` | Synchronized with release version |
| registry | string | `vars.HARBOR_HOST` | Harbor OCI registry |
| repository | string | `opsmill/chart` | Fixed OCI path |

**Publishing order**: Agent chart must be published before styrmin chart (styrmin depends on agent via OCI reference, rewritten by existing `publish-helm-chart.yml`).

## Relationships

```text
Version ─────── 1:1 ──────► Release
Release ─────── 1:1 ──────► Docker Image
Release ─────── 1:2 ──────► Helm Chart (styrmin + agent)
Docker Image ── 1:1 ──────► Cosign Signature
```

## Version Synchronization Flow

```text
1. Read version from pyproject.toml (source of truth)
2. Increment patch: 0.1.0 → 0.1.1
3. Write back to pyproject.toml
4. Write to helm/styrmin/Chart.yaml (version + appVersion)
5. Write to helm/agent/Chart.yaml (version)
6. Commit all changes to develop
7. Create git tag v0.1.1
8. Push commit + tag
```
