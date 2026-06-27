@AGENTS.md

## Active Technologies

- Python 3.14+ (backend, SDK, CLI); TypeScript 5.9.3 (frontend, Node 22) + Strawberry GraphQL, SQLModel + SQLAlchemy (async, asyncpg), Pydantic, Cyclopts (CLI), httpx (SDK), `dulwich` (git driver provider). Frontend: React 19, TanStack Query/Router, Radix UI, Tailwind. (013-driver-fingerprint)

- PostgreSQL via SQLModel/SQLAlchemy. Schema managed by `metadata.create_all()` — no Alembic migration required since Styrmin is not yet deployed in production. (013-driver-fingerprint)

- TypeScript (Docusaurus config), Markdown/MDX (content), Node.js 22+ + Docusaurus v3, `@easyops-ci/docusaurus-search-local`, pnpm (003-docs-site)

- N/A (static site, no database) (003-docs-site)

- TypeScript 5.9.3, Node 22 + React 19.2.4, `@tanstack/react-form` (new), `@tanstack/zod-form-adapter` (new), Zod 4.3.6, Radix UI, `@tanstack/react-query` v5 (001-tanstack-form-migration)

- Python 3.14+ + Pydantic v2, PyYAML, Jinja2, Prefect (001-consolidate-driver-format)

- Filesystem and Git (driver sources) — no database changes (001-consolidate-driver-format)

- TypeScript 5.9.3, Node 22 + React 19.2.4, TanStack Router 1.168.x (already installed), TanStack Query v5 (new), `@graphql-codegen/typescript-react-query` (new) (001-tanstack-query-migration)

- N/A (frontend-only, data via GraphQL API at `/graphql`) (001-tanstack-query-migration)

- Python 3.14+ + Pydantic v2, ariadne-codegen (build-time), httpx (Transport) (003-sdk-typed-bindings)

- Python 3.14+ + Strawberry GraphQL, SQLModel, SQLAlchemy (async), Pydantic, Jinja2 (001-cluster-env-capabilities)

- PostgreSQL via SQLModel — new JSON columns on Cluster and Environment tables (001-cluster-env-capabilities)

- TypeScript 5.9.3, React 19.2.4, Node 22 + `@tanstack/react-router` (new), urql 5.0.1, Radix UI, React Hook Form 7, Zod 4 (001-tanstack-router-migration)

- N/A (frontend-only change) (001-tanstack-router-migration)

- Python 3.14+ (backend, SDK, CLI) + Strawberry GraphQL, SQLModel, SQLAlchemy (async), Pydantic, Cyclopts (CLI), httpx (SDK transport) (001-graphql-name-lookup)

- PostgreSQL via SQLModel/SQLAlchemy (async). No Alembic -- schema managed via `metadata.create_all()`. (001-graphql-name-lookup)

- Python 3.14+ (backend), TypeScript 5.9.3 (frontend) + Strawberry GraphQL, SQLModel, Pydantic (backend); React 19, urql, React Hook Form, Zod, Radix UI (frontend) (002-single-cluster-limit)

- PostgreSQL via SQLModel/SQLAlchemy (async) — no schema/migration changes (002-single-cluster-limit)

- Python 3.14+ + Strawberry (GraphQL), Pydantic, SQLModel, Jinja2 (001-service-fqdn-context)

- PostgreSQL via SQLModel — no schema changes required (FQDNs are computed, not stored) (001-service-fqdn-context)

- Python 3.14+ + Cyclopts >=3.0.0 (already in project), Rich >=13.0.0, Pydantic-settings >=2.12.0, styrmin-sdk (local) (001-migrate-cli-cyclopts)

- N/A (CLI is a thin client over GraphQL API) (001-migrate-cli-cyclopts)

- TypeScript 5.9.3, React 19.2.4, Node 22 + Vite 8.0.1, urql 5.0.1 (GraphQL), Radix UI, React Router 7, React Hook Form 7 (058-frontend-testing)

- Python 3.14+ + Strawberry GraphQL, SQLModel, Loguru (backend); TypeScript + React 19 + TanStack Router + TanStack Query (frontend); no schema changes (011-admin-user-group-mgmt)

- TypeScript 5.9.3, React 19.2.4 + TanStack Query v5, Tailwind, lucide-react (frontend); reuses existing PodStatus GraphQL surface (012-deployment-pods-tab)

## Recent Changes

- 012-deployment-pods-tab: Added Pods tab to the deployment detail page — observed per-pod state grouped by component (declared / drifting / unlabeled per ADR-007), inline expand with container detail and copy-to-clipboard kubectl helpers, 10s auto-refresh paused when the tab is inactive
- 011-admin-user-group-mgmt: Added admin user/group GraphQL surface + auth UX (login, profile, role gating) on top of the #179 auth foundation
- 058-frontend-testing: Added TypeScript 5.9.3, React 19.2.4, Node 22 + Vite 8.0.1, urql 5.0.1 (GraphQL), Radix UI, React Router 7, React Hook Form 7
