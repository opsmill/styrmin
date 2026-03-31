@AGENTS.md

## Active Technologies

- Python 3.12+ (backend, SDK, CLI) + Strawberry GraphQL, SQLModel, SQLAlchemy (async), Pydantic, Cyclopts (CLI), httpx (SDK transport) (001-graphql-name-lookup)

- PostgreSQL via SQLModel/SQLAlchemy (async). No Alembic -- schema managed via `metadata.create_all()`. (001-graphql-name-lookup)

- Python 3.12+ (backend), TypeScript 5.9.3 (frontend) + Strawberry GraphQL, SQLModel, Pydantic (backend); React 19, urql, React Hook Form, Zod, Radix UI (frontend) (002-single-cluster-limit)

- PostgreSQL via SQLModel/SQLAlchemy (async) — no schema/migration changes (002-single-cluster-limit)

- Python 3.12+ + Strawberry (GraphQL), Pydantic, SQLModel, Jinja2 (001-service-fqdn-context)

- PostgreSQL via SQLModel — no schema changes required (FQDNs are computed, not stored) (001-service-fqdn-context)

- Python 3.12+ + Cyclopts >=3.0.0 (already in project), Rich >=13.0.0, Pydantic-settings >=2.12.0, styrmin-sdk (local) (001-migrate-cli-cyclopts)

- N/A (CLI is a thin client over GraphQL API) (001-migrate-cli-cyclopts)

- TypeScript 5.9.3, React 19.2.4, Node 22 + Vite 8.0.1, urql 5.0.1 (GraphQL), Radix UI, React Router 7, React Hook Form 7 (058-frontend-testing)

## Recent Changes

- 058-frontend-testing: Added TypeScript 5.9.3, React 19.2.4, Node 22 + Vite 8.0.1, urql 5.0.1 (GraphQL), Radix UI, React Router 7, React Hook Form 7
