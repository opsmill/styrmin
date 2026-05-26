# Contract: SDK / CLI / Frontend rendering — `<version>@<short>` display rule

**Phase**: 1 (Design & Contracts)
**Surface**: every user-facing rendering of an application driver version label.

## Display rule

A driver-version label is rendered as:

```
<version>@<short>
```

where `<short>` is the first 7 characters of the populated provenance fingerprint:

- `content_hash[:7]` when `source_type == "local"`.
- `source_commit_sha[:7]` when `source_type == "git"`.

The suffix is shown **unconditionally** — including when only one row exists for that `version` string. Reasoning: stable labels (the suffix never appears/disappears as siblings are loaded).

Detail surfaces additionally render the full fingerprint verbatim:

- Web: a copyable code element with a clipboard button.
- CLI default detail output: a labelled line (`Content hash: <64 chars>` or `Commit SHA: <40 chars>`).

## Helper signature (suggested)

To keep rendering consistent across surfaces, each consumer has a small helper that takes the API/SDK object and returns the formatted label.

**Backend / Python (CLI, future server-side renderers)**:

```python
def format_driver_version_label(*, version: str, content_hash: str | None,
                                source_commit_sha: str | None) -> str:
    fingerprint = content_hash or source_commit_sha
    if not fingerprint:
        return version          # only reachable for legacy NULL rows on dev DBs
    return f"{version}@{fingerprint[:7]}"
```

**Frontend / TypeScript** (in `frontend/src/lib/driverVersion.ts` or equivalent):

```typescript
export function formatDriverVersionLabel(
  v: { version: string; contentHash: string | null; sourceCommitSha: string | null }
): string {
  const fingerprint = v.contentHash ?? v.sourceCommitSha;
  if (!fingerprint) return v.version;          // legacy NULL fallback
  return `${v.version}@${fingerprint.slice(0, 7)}`;
}
```

## Surfaces that MUST adopt the helper

| Layer | Surface | File(s) (approximate) |
|---|---|---|
| Frontend | Driver list / version list | `frontend/src/components/drivers/VersionList.tsx`, `frontend/src/__tests__/driver-detail/VersionList.test.tsx` |
| Frontend | Driver detail page | `frontend/src/pages/drivers/DriverDetailPage.tsx`, plus an `OverviewTab` / `SourceTab` surface for the full fingerprint + copy button |
| Frontend | Deployment timeline + configuration edit drawer (driver-version reference) | `frontend/src/components/deployment/DeploymentTimeline.tsx`, `frontend/src/components/deployment/configuration/ConfigEditDrawer.tsx`, `frontend/src/components/deployment/configuration/sections/edit/IdentitySection.tsx` |
| CLI | `styrminctl driver list` | `cli/styrminctl/commands/driver.py` |
| CLI | `styrminctl driver get <id>` (detail) | same; render `Content hash` or `Commit SHA` line |
| CLI | `styrminctl deployment list` / detail (driver-version column) | `cli/styrminctl/commands/deployment.py` |
| SDK | Default human-readable repr of a generated `ApplicationDriverVersion` Pydantic model | Optional — only if any consumer relies on `repr()`; primary contract is to expose the underlying fields. |

## Tests

- Backend / CLI: snapshot/string-equality test that `format_driver_version_label("1.2.3", "a1b2c3d4...", None) == "1.2.3@a1b2c3d"`.
- Frontend: component test that asserts a label rendered for a fixture driver-version row contains the expected `<version>@<short>` text.
- Frontend: detail-surface test asserts the full fingerprint is visible (64-char or 40-char string) and a copy button is reachable.

## Backwards compatibility

- The suffix appears for all rows after this change. There is no flag to opt out.
- Users scripting against CLI output that previously parsed a version label as a bare `version` string MUST update to expect a possible `@<short>` suffix. The CLI MUST document this in its release notes and in the `dev/guides/driver-iteration.md` page introduced by this feature.
- The SDK does NOT change its semantic types — `version` remains a plain string. The label form is purely a presentational decision applied at rendering time.
