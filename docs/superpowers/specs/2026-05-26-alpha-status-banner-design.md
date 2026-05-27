# Alpha Status Banner & Page — Design

## Purpose

Communicate to docs visitors that Styrmin is currently in **alpha**, surface
the known limitations / broken features users are most likely to trip over,
and point them at the right channels for feedback and bug reports.

## Surfaces

### 1. Sitewide announcement banner

Use Docusaurus's built-in `themeConfig.announcementBar` (no new components).

Config added to `docs/docusaurus.config.ts` under `themeConfig`:

```ts
announcementBar: {
  id: 'alpha-status-v1',
  content:
    '🚧 Styrmin is in <strong>alpha</strong> — APIs and features may change. ' +
    '<a href="/docs/alpha-status">Read the alpha status →</a>',
  backgroundColor: '#fef3c7', // amber-100
  textColor: '#78350f',       // amber-900
  isCloseable: true,
},
```

- `id` is bumped (e.g. `alpha-status-v2`) when the message changes — that
  re-shows the banner to visitors who previously dismissed it.
- Closeable so returning visitors aren't nagged.
- The text/colour values are the only design call; both are conservative
  amber that work in light and dark mode.

### 2. New top-level docs page: `alpha-status.md`

Path: `docs/docs/alpha-status.md`.

Front matter:

```yaml
---
title: Alpha status
description: What "alpha" means for Styrmin today — known limitations, broken features, and how to give feedback.
---
```

Page outline:

1. **What alpha means** — short paragraph: APIs may change, breaking
   changes possible between releases, not suitable for
   production-critical workloads, expect rough edges. Set expectations.

2. **Limitations — coming before beta** (bullets, each links to the
   tracking issue):
   - Backup of a full environment — issue
     [opsmill/styrmin#7](https://github.com/opsmill/styrmin/issues/7).
   - Clone an environment — issue
     [opsmill/styrmin#6](https://github.com/opsmill/styrmin/issues/6).

3. **Known broken features**:
   - Infrahub Application backup is currently failing (Neo4j hook uses an
     Enterprise-only command against the Community image) — tracking issue
     [opsmill/styrmin#263](https://github.com/opsmill/styrmin/issues/263).

4. **Giving feedback / reporting bugs**:
   - Bugs & feature requests → [GitHub
     Issues](https://github.com/opsmill/styrmin/issues/new/choose).
     Contributors working in the repo should run the `create-issue` skill
     (`/create-issue`) — it formats the issue to project conventions and
     fills in the right labels.
   - General discussion, questions, feedback → OpsMill Discord at
     `https://discord.gg/opsmill`.

### 3. Sidebar update

In `docs/sidebars.ts`, insert `'alpha-status'` as a top-level item directly
between `'index'` and the Introduction category. It renders as a single
top-level link (no nested category), high-visibility, second only to
Welcome.

## What we are NOT doing

- No homepage / `index.mdx` rewrite. The banner + sidebar entry are
  sufficient.
- No new footer link, no navbar entry. Banner + sidebar already make the
  page reachable from every docs page.
- No custom React component or theme swizzle — `announcementBar` is
  out-of-the-box Docusaurus and Markdown handles the page.
- No new redirect rules. The page is new; nothing to redirect from.
- No changes to issue templates, README, or `AGENTS.md`.

## Acceptance

- Banner appears on every docs page on `pnpm start` and is dismissable.
- `/docs/alpha-status` resolves and lists the three issue links above as
  working external links.
- `pnpm build` succeeds with `onBrokenLinks: 'throw'` — meaning the
  banner-to-page link and the sidebar entry both resolve.
