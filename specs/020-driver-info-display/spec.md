# Feature Specification: Driver Logo, Description and Links

**Feature Branch**: `fac/feat-driver-logo-image-icon-field-model-h8bv3`

**Created**: 2026-10-08

**Status**: Draft

**Input**: GitHub issue [#272](https://github.com/opsmill/styrmin/issues/272) — "render driver logo/image from driver definition (icon field)", with these decisions made by the user before specification:

1. `spec.info.icon` holds an external `http`/`https` URL. Styrmin stores the URL as text on the **application driver version** and never fetches it. The browser of the person who views the page loads the image.
2. Styrmin stores and shows `icon`, `description` and `links` from `spec.info`. `authors` and `license` stay out of scope.
3. When a driver version has no logo, or the logo fails to load, the page shows the current generic package icon.

## Context

The **driver specification file** (`driver.styrmin.yml`) already accepts an optional `spec.info` block with `icon`, `description`, `authors`, `license` and `links`. Styrmin parses the block when a driver is loaded and then discards it:

- No column on the application driver version stores it.
- The GraphQL `ApplicationDriverVersion` type has no field for it.
- The driver list page shows the same generic package icon for every driver, and neither page shows the description or the links.
- The two example drivers that set `icon` use the placeholder value `xxxx`.

As a result, users who browse the driver list cannot tell applications apart at a glance, and users who open a driver cannot read what the application is or find its homepage and documentation from Styrmin.

## User Scenarios & Testing *(mandatory)*

The primary actor is **any signed-in user, including `READ_ONLY`**, who browses the driver list or opens a driver to choose what to deploy. The secondary actor is the **driver author**, who writes `spec.info` in the driver specification file and loads the driver.

### User Story 1 - Recognize each driver by its application's logo (Priority: P1)

A user opens the driver list page. Each driver shows the logo of its application next to its name, taken from the latest driver version. When the user opens a driver, the driver detail page shows the logo of the selected driver version in its header. A driver version without a logo, or with a logo that the browser cannot load, shows the generic package icon in the same place, so the layout does not change.

**Why this priority**: This is the outcome that issue #272 asks for. The logo is the fastest way to tell drivers apart in a list.

**Independent Test**: Load a driver whose specification file sets `spec.info.icon` to a reachable image URL, open the driver list page and the driver detail page, and check that both pages show that image. Load a second driver without `icon` and check that it shows the generic package icon.

**Acceptance Scenarios**:

1. **Given** a driver version whose specification file sets `spec.info.icon: https://example.com/logo.svg`, **When** the driver author loads it, **Then** the driver version stores that URL and returns it in the API.
2. **Given** a driver whose latest driver version has a logo URL, **When** a user opens the driver list page in the "Group by application" view, **Then** the driver's header shows that image instead of the generic package icon.
3. **Given** the same driver, **When** the user switches to the "Flat list" view, **Then** each row shows the logo of its own driver version next to the driver name.
4. **Given** a driver version with a logo URL, **When** a user opens it on the driver detail page, **Then** the page header shows that image next to the driver name.
5. **Given** a driver version without `spec.info.icon`, **When** a user opens the list or detail page, **Then** the page shows the generic package icon in the logo position.
6. **Given** a driver version whose logo URL returns an error or is not an image, **When** the browser fails to load it, **Then** the page replaces it with the generic package icon and does not show a broken-image marker.
7. **Given** two driver versions of the same driver with different logos, **When** a user switches between them on the detail page, **Then** the header shows the logo of the selected driver version.

---

### User Story 2 - Read what the application is and open its links (Priority: P2)

A user who browses the driver list reads a one-line description under each driver name. On the driver detail page, the user reads the full description of the selected driver version and views its links (for example "Homepage", "Documentation", "Github"). Selecting a link opens the target page in a new browser tab.

**Why this priority**: The description and links give context that the logo alone does not. They depend on the same storage and API work as the logo, but the logo is the user-visible goal of the issue.

**Independent Test**: Load a driver whose specification file sets `spec.info.description` and two `spec.info.links`, then check the list page for the description and the detail page for the description and both links.

**Acceptance Scenarios**:

1. **Given** a driver whose latest driver version has a description, **When** a user opens the driver list page in the "Group by application" view, **Then** the driver's header shows the description on one line, shortened with an ellipsis when it is longer than the space, and the full text is available on hover.
2. **Given** a driver version with a description, **When** a user opens it on the driver detail page, **Then** the page shows the full description as plain text above the tabs.
3. **Given** a driver version with links, **When** a user opens the detail page, **Then** the Overview tab lists each link by its label, in the order of the specification file.
4. **Given** a listed link, **When** the user selects it, **Then** the target opens in a new browser tab and the new page cannot control the Styrmin tab.
5. **Given** a driver version without a description or without links, **When** a user opens the detail page, **Then** the page does not show an empty description area or an empty links section.

---

### User Story 3 - Driver authors set and validate the logo, description and links (Priority: P2)

A driver author reads `driver/DRIVERS.md`, which describes the format of `spec.info.icon`, `spec.info.description` and `spec.info.links` with a working example. The author sets them in the driver specification file and loads the driver. When a value has the wrong format, loading fails with an error that names the field and the expected format, and Styrmin stores nothing for that load.

**Why this priority**: Without documentation and validation, authors copy the `xxxx` placeholder or set values that the UI cannot use. Validation also prevents a link or logo URL with a `javascript:` or `data:` scheme from reaching the browser.

**Independent Test**: Load a driver with `icon: xxxx`, then with `icon: javascript:alert(1)`, then with a link entry that has no `url`, and check that each load fails with an error that names the field. Load the `infrahub` example driver and check that it loads and shows its logo.

**Acceptance Scenarios**:

1. **Given** a specification file with `spec.info.icon` set to a value that is not an absolute `http` or `https` URL (for example `xxxx`, `logo.svg`, `javascript:alert(1)`, `data:image/png;base64,...`), **When** the driver author loads the driver, **Then** the load fails and the error names `spec.info.icon` and states that an `http` or `https` URL is required.
2. **Given** a specification file with a `spec.info.links` entry that does not have exactly the keys `link` and `url`, or whose `url` is not an absolute `http` or `https` URL, **When** the driver author loads the driver, **Then** the load fails and the error names the link entry.
3. **Given** the `infrahub` and `infrahub-enterprise` example drivers, **When** a driver author reads them, **Then** they set `spec.info.icon` to a real logo URL instead of `xxxx`.
4. **Given** `driver/DRIVERS.md`, **When** a driver author reads the `info` section, **Then** it states the accepted format of `icon`, `description` and `links`, that the browser of each viewer loads the logo from that URL, and the recommended image formats and size.

---

### User Story 4 - Driver versions loaded before this feature get their logo on reload (Priority: P3)

A platform engineer upgrades Styrmin. Driver versions that were loaded before the upgrade have no stored logo, description or links. When the engineer loads the same driver again (same commit for a Git source, same files for a local source), Styrmin keeps the existing driver version and fills in its logo, description and links from the specification file. The engineer does not have to push a new commit or change the driver version string.

**Why this priority**: Without it, every existing installation shows the generic icon for its existing drivers until each driver changes. It only affects installations that existed before this feature.

**Independent Test**: Create a driver version row without logo, description or links, then load a driver with the same source identity whose specification file sets all three, and check that the same driver version (same ID) now returns them.

**Acceptance Scenarios**:

1. **Given** a driver version stored before this feature, **When** the same driver source is loaded again and matches the stored driver version, **Then** Styrmin returns the same driver version with its logo, description and links filled in from the specification file.
2. **Given** a driver version that already has a logo, description and links, **When** the same driver source is loaded again, **Then** the stored values stay the same and no new driver version is created.

---

### Edge Cases

- **No `spec.info` block**: the driver loads as today. The pages show the generic icon, no description and no links.
- **`spec.info.icon` uses `http` instead of `https`**: accepted. When Styrmin is served over `https`, the browser can upgrade or block the image; the page then shows the generic icon.
- **Logo host is not reachable** (air-gapped installation, blocked domain, removed image): the page shows the generic icon and no error.
- **Very large or wide image**: the page scales it to fit the fixed logo area without changing the layout.
- **SVG logo with embedded script**: the browser loads the logo as an image, so it does not run scripts in the image.
- **Privacy of viewers**: loading the logo sends a request from each viewer's browser to the logo host. Styrmin asks the browser not to send the address of the Styrmin page with that request.
- **Logo host can see who views the driver pages**: a user who can load drivers chooses the logo host, and that host receives a request, with the viewer's IP address, each time someone opens a driver page. The driver author documentation tells authors to use an image host they trust.
- **Description with Markdown or HTML characters**: shown as plain text; no Markdown or HTML is rendered.
- **Long description on the list page**: shortened to one line, full text on hover. The detail page shows the full text and keeps line breaks from the specification file.
- **Link label or URL repeated**: listed as written; Styrmin does not remove duplicates.
- **Empty `links: []` or empty `description: ""`**: treated as not set.
- **Specification file with `authors` or `license`**: still accepted and still not stored.
- **Existing driver files with keys other than `link` and `url` in `links`**: now rejected at load time. All example drivers in this repository use `link` and `url`.
- **Driver versions with different logos within one driver**: the list header uses the latest driver version, chosen by the same order the list already uses for the "Latest" badge.
- **Filtering the list**: the filter keeps matching driver names, versions, sources and supported versions as today; it does not match the description.

## Requirements *(mandatory)*

### Functional Requirements

**Storage and loading**

- **FR-001**: When a driver is loaded, Styrmin MUST store `spec.info.icon`, `spec.info.description` and `spec.info.links` on the new application driver version.
- **FR-002**: Styrmin MUST NOT fetch, proxy or cache the logo image; it stores and returns only the URL.
- **FR-003**: Styrmin MUST reject a load whose `spec.info.icon` is not an absolute `http` or `https` URL, with an error that names `spec.info.icon`.
- **FR-004**: Styrmin MUST reject a load whose `spec.info.links` contains an entry without exactly the keys `link` (label text) and `url` (absolute `http` or `https` URL), with an error that names the entry.
- **FR-005**: A rejected load MUST NOT create or change any application driver, driver version, Helm chart or action record.
- **FR-006**: When a load matches an existing driver version by its source identity (the provenance fingerprint and source columns), Styrmin MUST update that driver version's logo, description and links to the values in the specification file, and MUST NOT create a new driver version.
- **FR-007**: Styrmin MUST treat an empty `description` or an empty `links` list as not set.
- **FR-008**: `authors` and `license` MUST stay accepted in the specification file and MUST NOT be stored.

**API**

- **FR-009**: The GraphQL `ApplicationDriverVersion` type MUST return the logo URL, the description and the list of links (label and URL) of the driver version, each empty or null when not set.
- **FR-010**: Driver versions stored before this feature MUST return null logo and description and an empty list of links until they are reloaded.

**Driver list page**

- **FR-011**: In the "Group by application" view, each driver header MUST show the logo of the driver's latest driver version in place of the generic package icon, and that driver version's description on one line, shortened with an ellipsis, with the full text on hover.
- **FR-012**: In the "Flat list" view, each row MUST show the logo of its driver version next to the driver name.

**Driver detail page**

- **FR-013**: The detail page header MUST show the logo of the selected driver version next to the driver name.
- **FR-014**: The detail page MUST show the full description of the selected driver version as plain text, and the Overview tab MUST list its links by label, in specification-file order.
- **FR-015**: Each link MUST open in a new browser tab, and the opened page MUST NOT receive a reference to the Styrmin tab.
- **FR-016**: The pages MUST NOT show an empty description area or an empty links section when the driver version has neither.

**Logo rendering and fallback**

- **FR-017**: Every place that shows a driver logo MUST show the generic package icon when the driver version has no logo or when the browser fails to load the image, in the same size and position.
- **FR-018**: Logos MUST be loaded as images (not as documents or frames) and marked as decorative (empty text alternative), because the driver name is always shown next to them as text. The browser MUST be asked not to send the Styrmin page address to the logo host.
- **FR-019**: Descriptions and link labels MUST be shown as plain text.

**Documentation and examples**

- **FR-020**: `driver/DRIVERS.md` MUST describe `spec.info.icon`, `spec.info.description` and `spec.info.links`: accepted formats, where each value appears in the UI, that each viewer's browser loads the logo from the given URL (so authors should use an image host they trust), and the recommended image format (square SVG or PNG) — with a working example.
- **FR-021**: The `infrahub` and `infrahub-enterprise` example drivers MUST set `spec.info.icon` to a real, publicly reachable logo URL, and no example or documentation page MUST keep the `xxxx` placeholder.
- **FR-022**: The public documentation pages under `docs/` that describe the driver specification file or the driver pages MUST describe the same fields and behavior.
- **FR-023**: The change MUST include two towncrier changelog fragments for #272: an "Added" entry for the logo, description and links, and a "Changed" entry stating that `spec.info.icon` and `spec.info.links` are now validated at load time.

### Key Entities

- **Application driver version**: gains three optional attributes taken from `spec.info` at load time — the logo URL, the description, and an ordered list of links. All three belong to one driver version, because two driver versions of the same driver can declare different values.
- **Driver link**: a label (for example "Documentation") and an absolute `http` or `https` URL. Ordered as in the specification file.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After loading the `infrahub` example driver, a user who opens the driver list page sees the Infrahub logo in that driver's header, with no other action.
- **SC-002**: In 100% of the following cases, the list and detail pages show the generic package icon and no broken-image marker: no `icon`, unreachable host, URL that returns an error, URL that returns a non-image.
- **SC-003**: 100% of loads with an `icon` or link `url` that is not an absolute `http` or `https` URL fail with an error that names the field, and store nothing.
- **SC-004**: A user can open an application's documentation from the driver detail page in one selection.
- **SC-005**: After an upgrade, reloading an unchanged driver fills in its logo, description and links on the existing driver version, with no new driver version created.
- **SC-006**: An end-to-end test that loads a driver with a logo and checks that the logo appears on the driver list page and on the driver detail page passes locally and in CI.

## Assumptions

- The logo belongs to the driver version, not to the application driver, because `spec.info` is part of each version's specification file. The list header, which represents the whole driver, uses the latest driver version.
- `http` is accepted in addition to `https`, as the user decided ("an http(s) URL"). Documentation recommends `https`.
- Styrmin does not add a Content-Security-Policy in this feature. Any logo host is allowed.
- The GraphQL schema exposes the new fields to any API client. The SDK's own operations and the CLI (`styrminctl`) output do not change in this feature.
- The description is not searched by the list filter.
- Other places that name a driver (the deploy form's driver selector, the deployment header) keep their current look. Showing the logo there is a possible follow-up.
- Styrmin does not limit the length of the description; the list page shortens it visually.
- Rejecting `icon` values that are not URLs, and `links` entries with other keys, can break third-party driver files that copied the `xxxx` placeholder. The changelog states it. Driver versions already stored are not checked again.
- The end-to-end test cannot depend on internet access from the test browser, so it uses a logo URL that the test environment serves itself.
