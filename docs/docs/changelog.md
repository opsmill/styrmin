---
title: Changelog
sidebar_position: 99
description: Notable user-visible changes to the Styrmin platform.
---

## Changelog

Notable user-visible changes are recorded here. For full commit history, see the [GitHub repository](https://github.com/opsmill/styrmin).

### Unified deployment Settings tab

The deployment detail page's **Parameters** tab has been replaced with a unified **Settings** tab.

#### What's new

- Settings shows the *effective* configuration that the application runs with — every value is walked through the **Cluster → Environment → Deployment** inheritance chain and attributed to the layer that defined it. Look for the small filled marker on rows the deployment layer explicitly overrides.
- A single right-side **Update Settings** drawer edits every deployment-scoped setting in one place: environment variables, services, driver parameters, scheduling, and per-component overrides.
- Every apply is gated by a **diff + impact** review dialog that classifies each change as informational, warning, or disruptive (with a static rule table) — no type-to-confirm friction.
- If another client modifies the deployment while you're editing, an inline conflict banner appears above your pending diff with a one-click **Reload** to merge against the new baseline. Your pending edits are preserved.

#### Migration

- The standalone **Scheduling** button has been removed from the deployment header. Scheduling now lives in the Settings tab alongside every other deployment-scoped setting — open the Settings tab and click **Update Settings**.
- The **Parameters** tab has been renamed to **Settings**. The same fields are editable from inside the unified drawer.
- A one-time hint banner explains the consolidation on first visit; click the **×** to dismiss it.

#### Known v1 scope limits

- **Networking** and **Storage & Runtime** are visible on the Settings tab but not editable from the drawer in v1 — they return in a follow-up when their nested-form UX is ready.
- **Per-component overrides** edit environment variables in v1; resource limits and replica counts return when the GraphQL surface exposes them.
