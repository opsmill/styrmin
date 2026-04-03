# Implementation Plan: Automated Daily Release Pipeline

**Branch**: `003-automated-release` | **Date**: 2026-04-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/003-automated-release/spec.md`

## Summary

Implement an automated daily release pipeline that bumps the patch version, creates a GitHub Release with auto-generated notes, builds and pushes a cosign-signed Docker image to Harbor, and publishes both Helm charts to the OCI registry. The pipeline is triggered by a daily cron schedule on `develop` (skipping if no new commits) and can also be triggered manually. It reuses the existing `publish-helm-chart.yml` workflow via `workflow_call` and leverages existing Harbor credentials.

## Technical Context

**Language/Version**: GitHub Actions (YAML workflows), Bash scripting for version logic
**Primary Dependencies**: GitHub Actions (actions/checkout, docker/build-push-action, sigstore/cosign-installer, azure/setup-helm), cosign (keyless signing via Sigstore), yq, Helm 3
**Storage**: N/A — CI/CD pipeline, no database
**Testing**: Manual `workflow_dispatch` triggers, GitHub Actions dry-run mode, version regression guard assertions
**Target Platform**: GitHub Actions runners (ubuntu-24.04 for x86_64 jobs, ubuntu-24.04-arm64 for ARM builds)
**Project Type**: CI/CD pipeline — workflow YAML files under `.github/workflows/`
**Performance Goals**: Complete release (version bump + Docker build + Helm publish) within 15 minutes of trigger
**Constraints**: Must reuse existing `publish-helm-chart.yml` via `workflow_call`; Harbor credentials already configured as `HARBOR_USERNAME`, `HARBOR_PASSWORD`, `HARBOR_HOST`; `pyproject.toml` is the single source of truth for version
**Scale/Scope**: 1 daily automated release; 2 new workflow files; 0 application code changes

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | N/A | No deployment logic — CI/CD pipeline only |
| II. Driver-Based Deployment | N/A | No driver changes |
| III. Layered Architecture | N/A | No application code changes |
| IV. Type Safety and Typed Errors | N/A | No Python/TypeScript code changes |
| V. Test-First Development | PASS | Workflow is testable via `workflow_dispatch`; version regression guard provides safety assertions |
| VI. Format and Lint Before Commit | PASS | Workflow YAML will pass `yamllint`; no Python code to lint |

**Governance Gates:**

| Gate | Status | Justification |
|------|--------|---------------|
| CI/CD workflow changes | ACKNOWLEDGED | This feature IS the CI/CD workflow — it's the entire scope. Discussed via GH issues #28 and #29. |
| New dependencies | ACKNOWLEDGED | `cosign` added as a GitHub Action (`sigstore/cosign-installer`) — required by FR-017 for supply chain security. No application dependencies added. |

**Boundaries:**

- No secrets committed — all credentials use existing GitHub secrets/variables
- No generated files edited manually
- No force pushes to `stable` or `develop` — release workflow pushes tags only

**Result: PASS** — No violations. Governance gates acknowledged with justification.

## Project Structure

### Documentation (this feature)

```text
specs/003-automated-release/
├── plan.md              # This file
├── research.md          # Phase 0: Research findings
├── data-model.md        # Phase 1: Entity/version model
├── quickstart.md        # Phase 1: Getting started guide
├── contracts/           # Phase 1: Workflow interface contracts
│   ├── release.yml      # Release workflow contract
│   └── docker-publish.yml  # Docker publish workflow contract
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
.github/workflows/
├── ci.yml                      # Existing — no changes
├── claude.yml                  # Existing — no changes
├── publish-helm-chart.yml      # Existing — reused via workflow_call (may need workflow_call trigger added)
├── release.yml                 # NEW — daily release orchestrator
└── docker-publish.yml          # NEW — Docker build, push, and cosign signing
```

**Structure Decision**: Pure CI/CD feature — all new code lives in `.github/workflows/`. No application source code changes. Version files (`pyproject.toml`, `helm/*/Chart.yaml`) are modified at runtime by the release workflow, not by committed code changes.

## Complexity Tracking

No constitution violations to justify — all gates pass.
