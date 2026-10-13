# Research: Driver Logo, Description and Links

All decisions below were made against the code on `develop` at `a2a627d3`. The three product decisions in the spec Input (external URL, icon + description + links, generic-icon fallback) are fixed and are not revisited here.

## R1. Storage shape on `ApplicationDriverVersion`

- **Decision**: Three nullable columns on `applicationdriverversion`:
  - `icon` — `AutoString` (text), the logo URL as the driver specification file wrote it after URL validation.
  - `description` — `AutoString` (text).
  - `links` — `JSON`, a list of `{"link": str, "url": str}` objects in specification-file order.
- **Rationale**: Matches how the table already stores per-version, doc-only spec data (`env_vars`, `container_overrides` are JSON columns; scalars are plain columns). Separate columns keep the scalar fields queryable and keep the GraphQL resolvers trivial. The values belong to the driver version, not to `ApplicationDriver`, because each version's specification file carries its own `spec.info`.
- **Alternatives considered**:
  - One `info` JSON column holding the whole block: rejected because `authors` and `license` are out of scope and would end up stored anyway, and the scalars become harder to read.
  - Columns on `ApplicationDriver`: rejected because two versions of one driver can declare different values, and the last load would overwrite the others.

## R2. Alembic revision and the current two-head state

- **Decision**: One revision adds the three columns and is also a **merge revision** with `down_revision = ("c2ff6dba5ffd", "f3a4b5c6d7e8")`.
- **Finding**: `command.heads()` on `develop` at `a2a627d3` reports two heads, `c2ff6dba5ffd` (widen backup size bytes) and `f3a4b5c6d7e8` (drop empty cluster dedicated ingress); both revise `e2f3a4b5c6d7`. With two heads, `styrmin db migrate` fails with "Multiple head revisions are present". `dev/guides/database-migrations.md` ("Multi-head resolution") prescribes a merge revision; `a8b9c0d1e2f3` is the worked example of a revision that merges two heads and adds schema.
- **Rationale**: A revision that names only one parent would leave the chain with two heads. Merging here restores a single head, which the new revision needs anyway.
- **Risk**: If `develop` gains its own merge revision before this branch lands, the rebase changes `down_revision` to that merge revision. A unit test that asserts a single head (R9) catches a missed rebase.
- **Outcome**: `develop` merged the two heads first, in `69b12221e5df`, and then added `3b926acd0791` (installation). On the rebase onto `develop`, the revision became a plain revision with `down_revision = "3b926acd0791"`.
- **Alternatives considered**: Fix the heads in a separate PR first — rejected because this branch cannot ship a revision without resolving them, and the guide treats merge-plus-schema as normal.

## R3. URL validation for `icon` and `links[].url`

- **Decision**: Use Pydantic `HttpUrl` for both `Info.icon` and `InfoLink.url`, set `Info.links: list[InfoLink] | None`, and give `InfoLink` `extra="forbid"` (already set). Persist `str(value)`.
- **Rationale**: `HttpUrl` accepts only absolute `http`/`https` URLs with a host, and rejects `xxxx`, `logo.svg`, `javascript:…` and `data:…`. The deserializer already turns `pydantic.ValidationError` into `DeserializationError("The driver specification is invalid: …")`, and Pydantic's message includes the location (`spec.info.icon`, `spec.info.links.0.url`), which satisfies FR-003/FR-004 with no new error type. `InfoLink` exists and is unused; using it removes the loose `list[dict[str, str]]`.
- **Normalization note**: `HttpUrl` normalizes some inputs (for example, `https://example.com` becomes `https://example.com/`, and the host is lower-cased). The stored value is the normalized URL. This does not change where the browser loads from.
- **Alternatives considered**:
  - A custom `str` validator that checks the scheme with `urllib.parse`: rejected; `HttpUrl` is the dependency's built-in mechanism for exactly this.
  - Accept only `https`: rejected; the user decided "an http(s) URL".

## R4. Empty `description` and empty `links`

- **Decision**: Normalize at the service layer: `description or None`, `links or None` before writing the row (FR-007). The GraphQL resolver returns `[]` for `links` when the column is NULL, and `null` for `description`.
- **Rationale**: One place decides "not set"; the UI never has to distinguish `""` from `null`.

## R5. Reload of an unchanged driver fills in the new fields (US4)

- **Decision**: In `load_application_driver_from_object`, when `get_by_identity` finds an existing row, assign `icon`, `description` and `links` from the parsed spec to that row when any of them differs, commit, and return the row (re-fetched with relationships).
- **Rationale**: The identity tuple pins the content: same `content_hash` for local drivers (the hash covers `driver.styrmin.yml` bytes) and same `source_commit_sha` for Git drivers. So a match means the specification file is byte-identical to the one that produced the row, except for rows stored before this feature, whose info columns are NULL. Assigning the parsed values is therefore a no-op for new rows and a backfill for old rows. Without it, every existing installation shows the generic icon until each driver changes.
- **Alternatives considered**:
  - Data migration that re-reads driver sources: rejected; the migration has no access to Git tokens or server-local driver paths.
  - Leave old rows empty: rejected because of the user impact described above (spec US4).

## R6. GraphQL field names

- **Decision**: On `ApplicationDriverVersion`:
  - `icon: String` — URL of the logo image.
  - `description: String`
  - `links: [DriverLink!]!` with `type DriverLink { label: String!, url: String! }`.
- **Rationale**: `icon` and `description` mirror `spec.info.<field>` one-to-one, as `envVars` and `containerOverrides` mirror their spec blocks. `DriverLink.label` is used instead of the file's `link` key, because `DriverLink.link` would read as "the link's link"; the field description states the mapping. Non-null list with `[]` for "none" follows `envVars`/`containerOverrides`.
- **Alternatives considered**: `iconUrl` — more explicit, but breaks the one-to-one mirror of the driver file that the rest of the type follows; the field description says it is a URL.

## R7. Logo rendering in the browser

- **Decision**: One shared `DriverLogo` component:
  - Renders `<img src={icon} alt="" referrerPolicy="no-referrer" loading="lazy" decoding="async">` inside a fixed-size frame with `object-contain`. The image is decorative because the driver name is always shown next to it (critique P4).
  - Tracks a `failed` state set by `onError`; when `icon` is null or `failed`, renders the lucide `Package` icon in the same frame.
  - Resets `failed` when `icon` changes (keyed by `icon`), so switching versions retries.
  - Exposes `data-testid="driver-logo"` and `data-logo-state="image|fallback"` for tests.
- **Rationale**:
  - Loading through `<img>` means SVG scripts do not run (browsers render SVG-as-image in secure static mode).
  - `referrerPolicy="no-referrer"` keeps the Styrmin page URL away from the logo host (spec edge case "Privacy of viewers", FR-018).
  - The fallback covers no icon, unreachable host, HTTP errors and non-image responses, because all of them fire `error` on `<img>` (SC-002).
- **Alternatives considered**: CSS `background-image` — rejected; it has no load-error event, so the fallback cannot trigger.

## R8. Where the logo, description and links appear

- **List page, grouped view**: the `AppGroup` header replaces `<Package/>` with `<DriverLogo>` for the latest-wins version and shows that version's description on one line (`truncate`, full text in `title`). The latest version must come from the full version set, not the filter-narrowed one, so `FilteredDriver` gains `latestVersion` next to the existing `latestVersionId`.
- **List page, flat view**: a small `<DriverLogo>` before the driver name in each row, for that row's version. No description (rows are per version, and the grouped view already shows it).
- **Detail page**:
  - `PageLayout` gains an optional `icon?: ReactNode` rendered before the `<h1>`; the detail page passes `<DriverLogo>` for the selected version.
  - The description renders as plain text with `whitespace-pre-line` between the header row and the tabs.
  - A "Links" section in `OverviewPanel` lists links as `<a target="_blank" rel="noopener noreferrer">`. It renders only when links exist.
- **Rationale**: The changes stay inside the existing components. `rel="noopener noreferrer"` satisfies FR-015. React escapes text, which satisfies FR-019.

## R9. Tests

- **Backend unit** (`backend/tests/unit/services/driver/`): `Info` accepts http/https URLs and rejects `xxxx`, `logo.svg`, `javascript:` and `data:` for `icon`; `links` rejects extra/missing keys and non-http(s) URLs; the loader error names the field.
- **Backend functional** (`backend/tests/functional/graphql/`, propagation guide):
  - Load a local driver with icon/description/links, then read the DB row and the GraphQL `applicationDriver { versions { icon description links { label url } } }`.
  - Seed a row without info, reload the same identity, and assert the same ID now carries the values (US4).
  - A pre-feature row returns `null`/`null`/`[]`.
  - A rejected load stores no driver version (FR-005).
- **Migration unit test** (`backend/tests/unit/db/`): the revision chain has exactly one head, and the head is the new revision.
- **Frontend** (Vitest + Testing Library):
  - `DriverLogo` renders the image, falls back on `error`, falls back on null, and retries on src change.
  - The list page shows the latest version's logo/description in the grouped view, even when the filter hides the latest version.
  - The detail page shows logo, description and links, and hides empty sections.
- **E2E** (R10).

## R10. E2E without internet access from the test browser

- **Decision**: Extend `backend/tests/e2e/test_ui_smoke.py` (ui-only, `shard_general`, uses the session `styrmin_resources` driver `simple-app`). The `git_server` fixture already rewrites `simple-app/driver.styrmin.yml` (Helm location) before committing it. It also sets `spec.info.icon` to a fixed test URL on a reserved domain (`https://styrmin-e2e.invalid/simple-app-logo.svg`) and adds one link. The test:
  1. Calls `page.route()` on that URL and serves a small inline SVG with `image/svg+xml` and explicit `width="24" height="24"`, so `naturalWidth` is not zero (critique E8).
  2. Opens `/drivers` and asserts that the `simple-app` header logo is in `data-logo-state="image"`, has that `src`, and has `naturalWidth > 0`.
  3. Opens `/drivers/<id>` and asserts the header logo, the description text and the link.
  4. Removes the route in `finally`, so a failed assertion does not leave it on the session page (critique E7).
- **Rationale**:
  - "Reuse before you boot": `styrmin_resources` and `session_ui_page` are already booted by active tests in the same file, so the new assertions add seconds, not a stack.
  - `page.route()` makes the browser load a real external-looking URL through the normal `<img>` path without depending on network access in CI. The `.invalid` TLD (RFC 2606) guarantees that no real host answers if the route is missing, which would make the test fail clearly instead of passing by accident.
- **Alternatives considered**:
  - Using the infrahub example's real URL: rejected; it needs internet access from the CI browser and would make the test flaky.
  - Asserting the `src` attribute only: rejected; it would not prove that the logo appears, and the fallback replaces the `<img>` when loading fails.
  - A new test file with its own driver: rejected per "Reuse before you boot".

## R11. Example drivers and documentation

- **Decision**: Set `spec.info.icon: https://docs.infrahub.app/img/infrahub-logo.svg` in `driver/examples/infrahub` and `driver/examples/infrahub-enterprise`, and replace the `xxxx` placeholder in `driver/DRIVERS.md`.
- **Finding**: That URL returns `200`, `content-type: image/svg+xml`, with a square `viewBox="0 0 24 24"` mark (checked 2026-10-08). It is served from OpsMill's own documentation site.
- **Docs to update**:
  - `driver/DRIVERS.md`: schema block, field table and example.
  - `docs/docs/drivers/creating-a-driver.md`: Step 2 example and notes.
  - `docs/docs/reference/driver-api.md`: the `spec.info` line.
  - `docs/docs/concepts-and-architecture/what-is-a-driver.md`: example `info` block.
- **Changelog**: `changelog/272.added.md` for the feature and `changelog/272.changed.md` for the stricter `icon`/`links` validation (critique X1).
- **Fixtures**: `backend/tests/unit/services/driver/fixtures/local_driver_directory/driver.styrmin.yml` and `fixtures/syntax/valid.yaml` use `icon: xxxx` and are switched to a valid `https` URL (critique E2).
- **Glossary**: `CONTEXT.md` gets a short **Driver logo** entry under "Application drivers", because the term appears in UI copy and docs.

## R12. Third-party dependency gaps

No dependency lacks a needed capability. Pydantic `HttpUrl` covers validation, SQLModel/Alembic cover the columns, Strawberry covers the type, the browser `<img>` element covers loading and failure detection, and Playwright `page.route()` covers the offline E2E. No extension or upstream change is needed.
