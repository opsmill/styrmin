---
title: Changelog
sidebar_position: 99
description: Notable user-visible changes to the Styrmin platform.
---

## Changelog

Notable user-visible changes are recorded here. For full commit history, see the [GitHub repository](https://github.com/opsmill/styrmin).

### Driver reload no longer requires bumping `version`

Application Driver Versions are now identified by a **provenance
fingerprint** in addition to their `spec.version` string. The
fingerprint is a SHA-256 content hash for local drivers and the
resolved git commit SHA for git drivers.

#### What's new

- Re-running `styrminctl drivers load-local-version <path>` on an
  edited driver records a new Application Driver Version row, even when
  `spec.version` is unchanged. Three files feed the content hash:
  `driver.styrmin.yml`, the values template, and `actions.py` (only
  when `spec.actions` is non-empty).
- Re-loading unchanged content is now a no-op — repeated loads no
  longer create duplicate rows and no longer crash with the cascade
  `IntegrityError` that used to surface on local reloads.
- Every driver-version label across the UI, CLI, and SDK is rendered as
  `<version>@<short-fingerprint>` (the first 7 hex chars). Detail
  surfaces show the full 64-char content hash or 40-char commit SHA
  with a copy-to-clipboard control.
- The `ApplicationDriverVersion` GraphQL type gains two nullable fields:
  `contentHash` (set for `sourceType == "local"`) and `sourceCommitSha`
  (set for `sourceType == "git"`). Exactly one is non-null per row.

#### Migration

- No action required. The new columns are nullable; legacy rows keep
  the bare `version` label until reloaded once.
- See [`dev/guides/driver-iteration.md`](https://github.com/opsmill/styrmin/blob/develop/dev/guides/driver-iteration.md)
  for the iteration-loop reference and the planned `drivers prune`
  follow-up.

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
