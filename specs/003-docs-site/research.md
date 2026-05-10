# Research: User-Facing Documentation Site

**Feature Branch**: `003-docs-site`
**Date**: 2026-04-03

## R-001: Docusaurus Project Location in Monorepo

**Decision**: Place Docusaurus project at `docs/` in the repo root with its own `package.json`.

**Rationale**: This is the standard convention used by major monorepos (React, Jest, Babel). The existing repo has `backend/` and `frontend/` at root level — `docs/` follows the same pattern. It keeps the documentation site independent from the frontend app (which uses Vite/React Router, not Docusaurus).

**Alternatives considered**:
- `documentation/` — Non-standard, no benefit over `docs/`
- Inside `frontend/` — Conflates the app with the docs; different build tools and dependencies
- Separate repository — Fragments the codebase; harder to keep docs in sync with code changes

## R-002: Search Implementation

**Decision**: Use `@easyops-ci/docusaurus-search-local` plugin.

**Rationale**: Docusaurus v3 has no built-in local search. This community plugin builds a lunr index at build time, requires zero external services, and is the most widely adopted solution for project-level docs. Algolia DocSearch is the "official" option but requires an external service and approval process — unnecessary for this project's scale.

**Alternatives considered**:
- Algolia DocSearch — Requires external service, approval queue, overkill for project docs
- Raw lunr.js — Requires custom integration; the plugin wraps this cleanly
- No search — Fails FR-011

## R-003: Sidebar Configuration Approach

**Decision**: Auto-generated sidebars with `_category_.json` metadata files.

**Rationale**: Auto-generated sidebars scale well and avoid maintaining a manual sidebar file that drifts from actual content. Category metadata files and numeric prefixes on filenames (e.g., `01-getting-started/`) provide explicit ordering control without manual sidebar maintenance.

**Alternatives considered**:
- Fully manual `sidebars.ts` — High maintenance burden, easy to drift from actual files
- Hybrid (some manual, some auto) — Adds complexity without clear benefit at this scale

## R-004: Deployment Target

**Decision**: GitHub Pages via GitHub Actions workflow.

**Rationale**: Consistent with OpsMill's existing project hosting. Modern approach uses `actions/upload-pages-artifact` + `actions/deploy-pages@v4` (not the legacy `gh-pages` branch). Workflow triggers on pushes to `develop` that touch `docs/**`.

**Alternatives considered**:
- Netlify/Vercel — Additional service dependency; GitHub Pages is sufficient
- Manual deployment — Error-prone, not scalable
- `gh-pages` branch method — Legacy approach, replaced by Actions Pages

## R-005: Existing Content to Migrate

**Decision**: Migrate `driver/DRIVERS.md` and `driver/examples/simple-app/` into the docs site. Internal `dev/knowledge/` files remain as developer-only documentation.

**Rationale**: `DRIVERS.md` (410 lines) is comprehensive driver documentation covering specs, templating, actions, and lifecycle. This is exactly the user-facing content needed for FR-006 through FR-009. The `dev/knowledge/` files are architecture internals not relevant to end users.

**Alternatives considered**:
- Migrate all dev/knowledge/ too — These are internal implementation docs, not user-facing
- Write driver docs from scratch — Wasteful when DRIVERS.md already exists and is comprehensive
- Symlink DRIVERS.md — Doesn't work with Docusaurus build process; content needs restructuring for the docs site navigation

## R-006: Package Manager Integration

**Decision**: Use pnpm for the docs site, consistent with the existing frontend.

**Rationale**: The frontend already uses pnpm. Using the same package manager avoids confusion and allows potential pnpm workspace integration. The `docs/` directory gets its own `package.json` with Docusaurus-specific dependencies.

**Alternatives considered**:
- npm — Inconsistent with existing frontend tooling
- yarn — Inconsistent with existing frontend tooling
