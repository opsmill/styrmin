# Research: Frontend Redesign

## Dark Mode with Tailwind CSS 4

**Decision**: Use CSS class strategy (`html.dark`) with CSS custom property overrides in `index.css`.
**Rationale**: Tailwind 4 uses `@theme` for token definitions. The simplest approach is defining light tokens at `:root` level and dark overrides in a `.dark` selector. This avoids any Tailwind config changes and works with the existing `@theme` directive.
**Alternatives considered**: `prefers-color-scheme` media query (rejected — design requires explicit user toggle), JS-based theme (rejected — CSS variables are more performant).

## Tab Component Approach

**Decision**: Simple `useState`-based tabs with no library.
**Rationale**: The tabs are page-level content switchers, not routed. Using state keeps it simple and preserves component state across tab switches. Base UI has no tab primitive in v1.3.0.
**Alternatives considered**: TanStack Router search params (over-engineering for tab state), headless UI tabs library (unnecessary dependency).

## Theme Persistence

**Decision**: `localStorage` with key `styrmin-theme`, default to `light`.
**Rationale**: Consistent with existing `sidebar-collapsed` localStorage pattern in AppShell. Apply class to `<html>` element on mount and toggle.
**Alternatives considered**: Cookie-based (unnecessary for SPA), CSS media query fallback (adds complexity without clear benefit for a developer tool).
