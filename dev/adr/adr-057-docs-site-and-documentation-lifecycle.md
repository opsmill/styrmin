# ADR-057: User-facing documentation in Docusaurus at `docs/`; `dev/knowledge/` stays internal

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/003-docs-site/research.md (R-001, R-005)

## Context

The project's documentation was scattered across three places before this decision:

- **`dev/knowledge/`** — architecture, services, data models, agent internals. Written for contributors who already work on the codebase. Detailed, jargon-heavy, assumes Python/Kubernetes/SQLModel context.
- **`dev/guides/`** — operational how-tos for contributors (pre-commit hooks, propagation tests, database migrations).
- **`driver/DRIVERS.md`** and `driver/examples/simple-app/` — comprehensive user-facing reference for driver authors. ~410 lines covering spec format, templating, actions, lifecycle. Sat at the top of the driver directory with no surfaced URL.

End users — operators deploying Styrmin, driver authors writing their own driver — had no canonical public site. Discoverability was poor (where do you go to find "how do I write a driver?"), and the contributor-oriented `dev/knowledge/` files were a confusing first hit for anyone searching.

The question was: introduce a separate documentation site for end users, and if so, what is the lifecycle between the new site and the existing `dev/` documentation?

## Decision

### Two parallel documentation surfaces with clear ownership

1. **`docs/`** at the repo root — a Docusaurus v3 project with its own `package.json`. Builds a public documentation site deployable to GitHub Pages. **This is for end users**: operators, driver authors, anyone consuming Styrmin from the outside.
2. **`dev/knowledge/`, `dev/guides/`, `dev/adr/`** — stay where they are. **This is for contributors**: people working in this repo. Internal architecture detail, operational hooks, decision history.

The split mirrors `backend/` and `frontend/` at root level — `docs/` is a peer, not nested inside either.

### Migration scope on first ship

- **Move**: `driver/DRIVERS.md` and `driver/examples/simple-app/` content gets restructured into the docs site under user-facing navigation. This is the comprehensive driver reference the docs site is built around.
- **Keep in place**: `dev/knowledge/` — architecture, services, data models — stays as contributor-only documentation. These are implementation internals, not end-user material.

### Ongoing lifecycle

- **User-facing content** (driver writing, operator workflows, deployment recipes) lives in `docs/`.
- **Internal architecture and decision history** (ADRs, knowledge, guides) lives in `dev/`.
- When the speckit `extract` workflow archives a spec, it writes decisions to `dev/adr/` and architectural knowledge to `dev/knowledge/` — not to `docs/`. Promoting something from `dev/` to `docs/` is a deliberate authoring step, not automatic extraction.
- `docs/` does **not** symlink or transclude `dev/knowledge/` files. The two have different audiences and different writing styles; trying to share source defeats the audience split.

### Build/deploy shape

- Docusaurus v3 with `@easyops-ci/docusaurus-search-local` for search (no external Algolia dependency).
- Auto-generated sidebar with `_category_.json` metadata files and numeric prefixes (`01-getting-started/`) for ordering — no hand-maintained `sidebars.ts`.
- Deployed to GitHub Pages via `actions/upload-pages-artifact` + `actions/deploy-pages@v4` (modern Pages, not the legacy `gh-pages` branch). Workflow triggers on pushes to `develop` that touch `docs/**`.
- pnpm for package management (consistent with `frontend/`).

## Consequences

- End users have a canonical URL for "where do I learn Styrmin?" — the docs site is the answer.
- Contributors keep their detailed internal documentation in `dev/` without having to rewrite it for a public audience or worry about leaking implementation detail to end users.
- The driver reference (`DRIVERS.md`) becomes navigable, searchable, and version-aware via the docs site instead of a single long Markdown file in the driver directory.
- `dev/knowledge/` and `dev/guides/` are unaffected by the docs site shipping — the speckit `extract` and `archive` workflows continue writing there with no per-file routing decision needed.
- Search is self-hosted (lunr.js via the plugin) — no Algolia approval queue, no external service dependency for a project-scale docs site.
- The docs site adds a `docs/` build pipeline to CI but does not affect any other workflow. The deploy is gated by `docs/**` path filter on `develop` pushes, so most PRs don't trigger it.
- **Promotion from `dev/` to `docs/` is manual by design** — when a contributor decides a `dev/knowledge/` page would be useful to end users, they author a new `docs/` page (often a different shape, different examples, less jargon). Mechanical duplication would produce confusing material on the public site.
- The pattern composes for future user-facing surfaces: a CLI reference, a GraphQL schema browser, etc. — all live under `docs/`, not in `dev/`.

## Alternatives Considered

- **Single documentation surface combining `dev/` and end-user docs**: rejected. Two audiences with different needs, jargon levels, and stability expectations. A combined surface would either over-expose internals to end users or dumb-down internal docs for contributors.
- **`documentation/` directory name**: rejected. Non-standard; major monorepos (React, Jest, Babel) use `docs/`.
- **`docs/` nested inside `frontend/`**: rejected. The frontend uses Vite + React Router; Docusaurus is a separate React-based static-site generator with its own build tooling. Conflating them produces a confusing build graph.
- **Separate repository for docs**: rejected. Fragments the codebase; docs would drift from the code they document. Keeping docs alongside the implementation forces the same PR that changes behaviour to update the user-facing reference.
- **Symlink or transclude `dev/knowledge/` files into `docs/`**: rejected. The two surfaces have different audiences; the source text for "how the deployment context works for driver authors" should not be the same as "how the deployment context works in the internal codebase". Sharing source forces one of them to be the wrong shape.
- **Migrate `dev/knowledge/` into `docs/` and abandon `dev/knowledge/`**: rejected. `dev/knowledge/` exists for AI agents and human contributors orienting in the codebase — its level of detail and assumed context is wrong for end users. Moving it would either ship internals to the public site or destroy the contributor reference.
- **Algolia DocSearch instead of local search**: rejected. Requires external service, application/approval process, and management of an indexer crawl. Overkill for project-scale documentation; the local-search plugin is self-contained.
- **Manual `sidebars.ts`**: rejected. High-maintenance, drifts from actual files. Auto-generation with `_category_.json` and numeric prefixes gives explicit ordering control without manual sync.
- **Legacy `gh-pages` branch deployment**: rejected. The modern `actions/deploy-pages@v4` flow is cleaner, doesn't pollute git history with built artifacts, and is the path GitHub itself recommends.
