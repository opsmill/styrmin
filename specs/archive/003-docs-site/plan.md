# Implementation Plan: User-Facing Documentation Site

**Branch**: `003-docs-site` | **Date**: 2026-04-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/003-docs-site/spec.md`

## Summary

Create a Docusaurus v3 documentation site for Styrmin, providing Getting Started guides, installation instructions for 5 Kubernetes platforms, and Application Driver documentation. The site lives at `docs/` in the repo root, uses auto-generated sidebars, local search via `@easyops-ci/docusaurus-search-local`, and deploys to GitHub Pages via GitHub Actions.

## Technical Context

**Language/Version**: TypeScript (Docusaurus config), Markdown/MDX (content), Node.js 22+
**Primary Dependencies**: Docusaurus v3, `@easyops-ci/docusaurus-search-local`, pnpm
**Storage**: N/A (static site, no database)
**Testing**: Manual content review, build verification (`pnpm build` succeeds), link checking
**Target Platform**: Static web — GitHub Pages
**Project Type**: Documentation site within existing monorepo
**Performance Goals**: Page load < 3 seconds on standard broadband (SC-005)
**Constraints**: Must align with OpsMill project styling; must use Docusaurus per FR-001
**Scale/Scope**: ~15-20 Markdown pages across 4 sections

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applies? | Status |
|-----------|----------|--------|
| I. Declarative State Reconciliation | No | N/A — documentation site, no deployment logic |
| II. Driver-Based Deployment | No | N/A — documenting drivers, not modifying them |
| III. Layered Architecture | No | N/A — no backend code changes |
| IV. Type Safety and Typed Errors | No | N/A — no Python/GraphQL changes |
| V. Test-First Development | Partial | Build verification serves as the test; no unit tests needed for static content |
| VI. Format and Lint Before Commit | Yes | **PASS** — will configure ESLint/Prettier for docs if applicable; Markdown linting optional |

**Governance Gates**:
- New dependencies: **YES** — Docusaurus and search plugin are new Node.js dependencies, but isolated in `docs/package.json` with no impact on backend or frontend
- CI/CD workflow changes: **YES** — new GitHub Actions workflow for docs deployment, isolated from existing CI

**Verdict**: All gates pass. This feature is entirely additive — a new `docs/` directory with its own dependencies and build. No modifications to existing backend, frontend, or infrastructure code.

## Project Structure

### Documentation (this feature)

```text
specs/003-docs-site/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── README.md
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
docs/                           # New Docusaurus project
├── docusaurus.config.ts        # Site config (title, URL, navbar, footer)
├── sidebars.ts                 # Auto-generated sidebar config
├── package.json                # Docusaurus + search plugin dependencies
├── tsconfig.json               # TypeScript config for Docusaurus
├── docs/                       # Markdown content
│   ├── getting-started/
│   │   ├── _category_.json
│   │   ├── overview.md         # Platform overview, core concepts
│   │   └── quickstart.md       # Fastest path to running Styrmin
│   ├── installation/
│   │   ├── _category_.json
│   │   ├── prerequisites.md    # Common prerequisites
│   │   ├── eks.md              # Amazon EKS guide
│   │   ├── gke.md              # Google GKE guide
│   │   ├── aks.md              # Azure AKS guide
│   │   ├── k3s.md              # k3s guide
│   │   └── kubeadm.md          # kubeadm guide
│   └── drivers/
│       ├── _category_.json
│       ├── what-is-a-driver.md # Conceptual overview
│       ├── creating-a-driver.md # Step-by-step guide
│       ├── specification.md    # Field reference (from DRIVERS.md)
│       └── example-walkthrough.md # Complete example
├── src/
│   ├── css/
│   │   └── custom.css          # OpsMill brand colors
│   └── pages/
│       └── index.tsx           # Custom homepage
└── static/
    └── img/
        └── logo.svg            # OpsMill/Styrmin logo
```

**Structure Decision**: New `docs/` directory at repo root, completely isolated from existing `backend/` and `frontend/`. Uses its own `package.json` and build pipeline. This follows the convention of major monorepos and avoids any coupling with the existing frontend app.

## Complexity Tracking

No constitution violations. No complexity justifications needed.
