# ADR-067: Driver Logos Are Third-Party URLs That Each Viewer's Browser Loads

**Status**: Accepted
**Date**: 2026-10-13
**Source**: [issue #272](https://github.com/opsmill/styrmin/issues/272); specs/archive/020-driver-info-display/ (spec Input decisions 1-3, Edge Cases, FR-001, FR-002, FR-017, FR-018, Assumptions; research R1, R4, R7; critique P3, P4, E4); commit `8a166997` (review of PR #418)
**Related**: [ADR-068](0068-invalid-driver-info-dropped-with-load-warning.md) (what a load does with an invalid `icon` or `links` value), [ADR-053](0053-driver-version-provenance-fingerprint.md) (a reload of an unchanged driver fills in these columns)

## Context

The driver specification file (`driver.styrmin.yml`) accepted an optional `spec.info` block with `icon`, `description`, `authors`, `license` and `links`. Styrmin parsed the block when it loaded a driver and then discarded it. Every driver showed the same generic package icon, no page showed a description or links, and the example drivers set `icon` to the placeholder `xxxx`.

Issue #272 asked for the driver pages to show the driver's logo. Before the specification was written, the user decided three things:

1. `spec.info.icon` holds an external URL. Styrmin stores the URL as text on the application driver version and never fetches it. The browser of the person who views the page loads the image.
2. Styrmin stores and shows `icon`, `description` and `links`. `authors` and `license` stay out of scope.
3. When a driver version has no logo, or the logo fails to load, the page shows the generic package icon.

## Decision

1. **Three nullable columns on each application driver version** (`ApplicationDriverVersion`, Alembic revision `c62923f4dc7e`):
   - `icon`: the logo URL, as text.
   - `description`: text.
   - `links`: JSON, a list of `{"link", "url"}` entries in the order of the specification file.

   The values belong to the driver version, not to the application driver, because each version's specification file has its own `spec.info`. An empty `description` or an empty `links` list is stored as NULL. The columns are not part of the driver version identity.
2. **Styrmin never fetches, proxies or caches the image** (FR-002). It stores the URL and returns it through the GraphQL `ApplicationDriverVersion.icon` field.
3. **The browser loads the logo through an `<img>` element**, in the shared `DriverLogo` component (`frontend/src/pages/drivers/DriverLogo.tsx`):
   - `alt=""`, because the driver name is always shown next to the logo as text (critique P4).
   - `referrerPolicy="no-referrer"`, so the browser does not send the address of the Styrmin page to the logo host.
   - The generic package icon shows while the image loads, when the driver version has no logo, and when the browser fails to load the image.

   An SVG loaded as an image does not run scripts. An `<img>` reports a load error for an unreachable host, an HTTP error and a response that is not an image, so one error handler covers every case in which the fallback must show.
4. **The icon must be an absolute `https` URL.** Links may use `http` or `https`. Neither may contain a username or password. The specification accepted `http` for the icon, as the user had decided; commit `8a166997` changed this during the review of PR #418. `driver/DRIVERS.md` gives the reason: a Styrmin server served over HTTPS cannot show an `http` image, because browsers block it as mixed content. ADR-068 records what a load does with a value that breaks these rules.
5. **No Content-Security-Policy is added.** Any logo host is allowed (spec Assumptions).
6. **An operator can stop the logo requests for the whole installation.** When `STYRMIN_DRIVER_SHOW_LOGOS` is false (Helm value `styrmin.driver.showLogos`, default `true`), the API returns `icon: null` for every driver version, so no browser requests a logo. The stored URLs are kept, so turning the setting back on shows the logos again without reloading the drivers. Commit `8a166997` added this setting.

## Consequences

- The logo host receives a request, with the viewer's IP address, each time someone opens a page that shows the logo. The person who loads the driver chooses the host; both load mutations (`loadLocalApplicationDriverVersion`, `loadRemoteApplicationDriverVersion`) require the `ADMIN` role. `driver/DRIVERS.md` tells driver authors to use an image host they trust, and the setting in decision 6 lets an operator stop the requests.
- An installation without internet access shows the generic icon, unless the driver points at an image on an internal host.
- The example drivers point at `https://docs.infrahub.app/img/infrahub-logo.svg`.
- Driver versions stored before this decision return no logo, description or links until their driver is loaded again. The reload fills in the existing row instead of creating a new one (ADR-053, amended).
- The GraphQL fields are available to every API client. `links` returns an empty list when the column is NULL.

## Alternatives Considered

- **Store an image file inside the driver**: the user chose external URLs before the specification was written (critique P3).
- **Fetch, proxy or cache the image in Styrmin**: excluded by the user's first decision (FR-002). The sources record no further evaluation of it.
- **CSS `background-image` instead of `<img>`**: rejected, because it has no load-error event, so the fallback could not show (research R7).
- **One `info` JSON column for the whole block**: rejected, because `authors` and `license` would be stored too, and the scalar values would be harder to read (research R1).
- **Columns on `ApplicationDriver`**: rejected, because two versions of one driver can declare different values, and the last load would overwrite the others (research R1).
- **Accept `http` for the icon**: the specification's decision, replaced by decision 4.
