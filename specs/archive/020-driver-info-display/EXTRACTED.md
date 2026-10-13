# Extraction Record

**Extracted on**: 2026-10-13
**Extracted by**: speckit.opsmill.extract

Commit `8a166997`, from the review of PR #418, replaced research R3 and spec FR-003 to FR-005: an
invalid `icon` or `links` value is dropped with a load warning instead of failing the load. The
ADRs and knowledge below record what shipped.

## ADRs Created

- [dev/adr/0067-driver-logos-loaded-by-the-viewer-browser.md](../../../dev/adr/0067-driver-logos-loaded-by-the-viewer-browser.md) (from R1, R4, R7, the spec Input decisions and Assumptions, and commit `8a166997`)
- [dev/adr/0068-invalid-driver-info-dropped-with-load-warning.md](../../../dev/adr/0068-invalid-driver-info-dropped-with-load-warning.md) (from R3 as shipped and commit `8a166997`)

## ADRs Amended

- [dev/adr/0053-driver-version-provenance-fingerprint.md](../../../dev/adr/0053-driver-version-provenance-fingerprint.md) (§4 and Consequences: a reload of an unchanged driver writes `icon`, `description` and `links` when they differ; from R5)

## Knowledge Updated

- `dev/knowledge/backend/services.md` (Applications Service: corrected "idempotent no-op"; new "Driver information in `spec.info`"; Deserializers)
- `dev/knowledge/backend/api.md` (load mutation rows; new "ApplicationDriverVersion: logo, description, links and load warnings")
- `dev/knowledge/backend/data-models.md` (ApplicationDriverVersion)
- `dev/knowledge/backend/overview.md` (Settings loading: `DriverSettings.show_logos`)
- `dev/knowledge/frontend/driver-pages.md` (new file)
- `dev/knowledge/frontend/ui-primitives.md` (new "Clamped text with "Show more" (`ClampedText`)" and "Warning notifications (`toast.tsx`)")
- `dev/knowledge/backend/e2e-testing.md` (Git Server; new "Serving external URLs to the UI browser")
- `dev/knowledge/cli/overview.md` (new "Driver load warnings")

## Guidelines Updated

- `dev/guidelines/backend/python.md` (Validate URLs that a browser loads or opens)
- `dev/guidelines/frontend/ui-primitives.md` (new "Links That Open a New Tab" and "Driver Logos")

## Other Changes

- `dev/guides/driver-iteration.md`: the "reload is a no-op" statements now name the exception for the three info columns.
- `backend/styrmin_backend/db/models.py`: the `icon` comment says the URL must be an absolute `https` URL.

## Already Documented Before Extraction

- `driver/DRIVERS.md` (`spec.info` fields), `docs/`, `CONTEXT.md` (Driver logo, Load warning), changelog fragments

## spec.md Changes at Extraction

- `**Status**` set to `Extracted`.

## Archive

Spec directory moved to `specs/archive/020-driver-info-display/` as a historical record.
