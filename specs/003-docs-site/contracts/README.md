# Contracts: User-Facing Documentation Site

This feature does not introduce API contracts (no REST endpoints, GraphQL mutations, or service interfaces). The documentation site is a static site generated from Markdown content.

## Content Contract

The only "contract" is the content structure that Docusaurus expects:

- **Markdown files** with YAML frontmatter (`title`, `sidebar_position`, etc.)
- **Category metadata** via `_category_.json` files in each section directory
- **Docusaurus config** via `docusaurus.config.ts` at `docs/` root

## Build Contract

- `pnpm build` in `docs/` produces a static site in `docs/build/`
- The build output is a self-contained static site deployable to any static hosting
- GitHub Actions deploys the `docs/build/` output to GitHub Pages on pushes to `develop`
