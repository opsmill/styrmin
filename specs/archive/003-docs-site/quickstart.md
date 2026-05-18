# Quickstart: User-Facing Documentation Site

**Feature Branch**: `003-docs-site`
**Date**: 2026-04-03

## Prerequisites

- Node.js 22+ (already used by the frontend)
- pnpm (already used by the frontend)

## Setup

```bash
# From repo root
cd docs
pnpm install
```

## Development

```bash
# Start local dev server (hot reload)
pnpm start
```

The site will be available at `http://localhost:3000/` (or the configured `baseUrl`).

## Build

```bash
# Generate static site
pnpm build

# Preview the built site locally
pnpm serve
```

## Adding Content

1. Create a new `.md` file in the appropriate `docs/docs/` subdirectory
2. Add frontmatter with `title` and `sidebar_position`
3. The sidebar auto-generates from the file structure

## Adding a New Section

1. Create a new directory under `docs/docs/`
2. Add a `_category_.json` with `label` and `position`
3. Add Markdown files inside the directory

## Project Structure

```text
docs/
├── docusaurus.config.ts    # Site configuration
├── sidebars.ts             # Auto-generated sidebar config
├── package.json            # Docusaurus dependencies
├── docs/                   # Markdown content
│   ├── getting-started/
│   ├── installation/
│   └── drivers/
├── src/
│   └── pages/              # Custom pages (homepage)
└── static/
    └── img/                # Images, logos
```
