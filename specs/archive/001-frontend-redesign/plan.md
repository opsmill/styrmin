# Implementation Plan: Frontend Redesign with Dark/Light Mode

**Branch**: `001-frontend-redesign` | **Date**: 2026-04-06
**Input**: Paper design mockups (14 artboards covering Dashboard, Environment Detail, Deployment Detail in light/dark)

## Summary

Redesign the Styrmin frontend to support dark/light mode theming and improve information architecture across all major pages. The redesign introduces tabbed navigation at the page level (Environment Detail gets Overview/Parameters/Backups tabs; Deployment Detail gets Overview/Parameters/Backups/Timeline tabs), access-focused endpoint display, and a consistent parameter card grid pattern. All changes are frontend-only — no GraphQL schema or backend modifications required.

## Technical Context

**Language/Version**: TypeScript 5.9, React 19
**Primary Dependencies**: Tailwind CSS 4, Base UI, TanStack Router, TanStack Query, Lucide React, CVA
**Storage**: N/A (frontend-only, data from existing GraphQL API)
**Testing**: Vitest, React Testing Library
**Target Platform**: Web (desktop browsers)
**Project Type**: Web application (frontend only)
**Performance Goals**: No new network requests, theme switch must be instant (CSS-only)
**Constraints**: Must use existing GraphQL queries/types unchanged, no new dependencies
**Scale/Scope**: ~15 files modified, ~5 new component files

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Notes |
|------|--------|-------|
| Database schema changes | PASS | No database changes |
| GraphQL schema modifications | PASS | No schema changes — uses existing queries |
| New dependencies | PASS | No new npm packages needed |
| CI/CD workflow changes | PASS | No CI changes |
| Authentication/authorization | PASS | No auth changes |
| Format and lint | PASS | Will run `cd frontend && pnpm lint` before commit |
| Test-first development | PASS | Will add/update component tests |

## Project Structure

### Documentation (this feature)

```text
specs/001-frontend-redesign/
├── plan.md              # This file
├── research.md          # Phase 0 output
└── data-model.md        # N/A — no data model changes
```

### Source Code (affected files)

```text
frontend/src/
├── index.css                              # MODIFY: Add dark theme CSS vars, .dark selector
├── App.tsx                                # MODIFY: Wrap with ThemeProvider
├── hooks/
│   └── use-theme.ts                       # CREATE: Theme context + hook
├── components/
│   ├── AppShell.tsx                        # MODIFY: Redesign sidebar + add theme toggle
│   ├── PageLayout.tsx                      # MODIFY: Remove header border, simplify
│   ├── ui/
│   │   └── tabs.tsx                        # CREATE: Reusable tab component
│   ├── ThemeToggle.tsx                     # CREATE: Sun/moon toggle button
│   ├── ParameterCards.tsx                  # CREATE: Reusable parameter card grid
│   └── EmptyState.tsx                      # MODIFY: Support "coming soon" variant
├── pages/
│   ├── environments/
│   │   ├── EnvironmentListPage.tsx         # MODIFY: Card redesign + recent activity
│   │   └── EnvironmentDetailPage.tsx       # MODIFY: Add tabs, move apps to Overview
│   └── deployments/
│       └── DeploymentDetailPage.tsx        # MODIFY: Add tabs, redesign Overview
```

**Structure Decision**: Frontend-only changes within the existing `frontend/src/` structure. No new directories needed — new components go in existing `components/` directory.

## Design Decisions

### 1. Dark Mode Implementation

Use CSS class strategy (`html.dark`) with `localStorage` persistence. Tailwind CSS 4's `@theme` in `index.css` will define light tokens in `:root` and dark tokens in `.dark`. No runtime JS needed for color computation — pure CSS variable swap.

**Why not media query (`prefers-color-scheme`)?** The design includes an explicit toggle, so user preference should override system setting.

### 2. Theme Color Tokens

Light mode:
- Background: `#ffffff`, Surface: `#FAFAFA`, Border: `#E8E8EC`
- Primary: `#1A1A2E` (navy), Text: `#1A1A2E` / `#71717A` / `#A1A1AA`

Dark mode:
- Background: `#0F1117`, Surface: `#161621`, Border: `#25253A`
- Primary: `#6366F1` (indigo), Text: `#E4E4E7` / `#A1A1AA` / `#52525B`

### 3. Tab Component

Simple unstyled tab component using `useState` — no library needed. Active tab has bottom border indicator. Tab content is conditionally rendered (not routed) to preserve scroll position.

### 4. Parameter Card Grid

Reusable `ParameterCards` component used by both Environment Detail and Deployment Detail Parameters tabs. Shows key (monospace), value, description, and type badge with color coding (string=red, integer=indigo, boolean=amber, select=teal).

### 5. "Coming Soon" Pattern

Backups tab on Environment Detail shows a centered empty state with icon, description, and "Coming soon — currently in development" pill. Tab label shows a small `SOON` badge.

## Phases

### Phase 1: Theme Infrastructure
1. Update `index.css` with dark theme CSS variables
2. Create `use-theme.ts` hook (context + localStorage)
3. Create `ThemeToggle.tsx` component
4. Update `App.tsx` to wrap with theme provider
5. Update `AppShell.tsx` with new sidebar design + theme toggle

### Phase 2: Shared Components
6. Create `tabs.tsx` UI component
7. Create `ParameterCards.tsx` component
8. Update `EmptyState.tsx` with "coming soon" variant

### Phase 3: Environment Pages
9. Redesign `EnvironmentListPage.tsx` (cards + activity table)
10. Redesign `EnvironmentDetailPage.tsx` (tabs: Overview, Parameters, Backups)

### Phase 4: Deployment Page
11. Redesign `DeploymentDetailPage.tsx` (tabs: Overview with endpoints + timeline, Parameters, Backups, Timeline)

### Phase 5: Polish & Test
12. Update existing tests for changed components
13. Run linter and fix any issues
14. Visual review of all pages in both themes
