# Data Model: Driver Logo, Description and Links

## Driver specification file (input) — `spec.info`

Pydantic models in `backend/styrmin_backend/services/driver/models/resources/driver.py`.

| Field | Type after this change | Before | Stored |
|-------|------------------------|--------|--------|
| `icon` | `HttpUrl \| None` | `str \| None` | Yes, as `str(icon)` |
| `description` | `str \| None` | same | Yes; `""` stored as NULL |
| `links` | `list[InfoLink] \| None` | `list[dict[str, str]] \| None` | Yes, as `[{"link", "url"}]`; `[]` stored as NULL |
| `authors` | `list[str] \| None` | same | No (out of scope) |
| `license` | `str \| None` | same | No (out of scope) |

`InfoLink` (existing, `extra="forbid"`): `link: str` (label text), `url: HttpUrl`.

Validation rules:

- `icon` and `links[].url` MUST be absolute `http`/`https` URLs with a host. `HttpUrl` rejects every other value; the loader raises `DriverLoadingError` (via `DeserializationError`) with Pydantic's location (`spec.info.icon`, `spec.info.links.<n>.url`, `spec.info.links.<n>.<key>`).
- A `links` entry MUST have exactly `link` and `url`.
- Validation runs before any database write, so a rejected load stores nothing (FR-005).

## `ApplicationDriverVersion` (database) — new columns

Table `applicationdriverversion`, model in `backend/styrmin_backend/db/models.py`.

| Column | SQL type | Nullable | Default | Source |
|--------|----------|----------|---------|--------|
| `icon` | `VARCHAR` (`AutoString`) | yes | NULL | `str(spec.info.icon)` |
| `description` | `VARCHAR` (`AutoString`) | yes | NULL | `spec.info.description or None` |
| `links` | `JSON` | yes | NULL | `[l.model_dump(mode="json") for l in spec.info.links] or None` |

- Not part of the identity tuple or the unique index `uq_application_driver_version_identity`: the provenance fingerprint already covers the specification file's bytes or commit.
- Rows stored before this feature carry NULL in all three.

### Write paths

1. **New identity** — `load_application_driver_from_object` creates the row with the three values.
2. **Existing identity** (`get_by_identity` hit) — the service assigns the three parsed values to the existing row when any differs, commits, and returns the re-fetched row (research R5). No other column changes.
3. **Concurrent-insert race** (`IntegrityError` branch) — returns the winner's row unchanged; the winner wrote the same values from the same content.

### Migration

One Alembic revision in `backend/styrmin_backend/db/migrations/versions/`:

- `down_revision = ("c2ff6dba5ffd", "f3a4b5c6d7e8")` — merges the two current heads (research R2).
- `upgrade()`: `add_column` × 3, all nullable, no default, so it is safe on a populated table.
- `downgrade()`: `drop_column` × 3.

## GraphQL projection

`ApplicationDriverVersion` (Strawberry, `backend/styrmin_backend/api/definitions/application_driver/model.py`):

| GraphQL field | Type | From |
|---------------|------|------|
| `icon` | `String` | `instance.icon` |
| `description` | `String` | `instance.description` |
| `links` | `[DriverLink!]!` | `instance.links or []`, each `{"link","url"}` → `DriverLink(label=link, url=url)` |

New type `DriverLink { label: String!, url: String! }`.

## Frontend view model

- `ListDrivers` query adds `icon` and `description` to `versions`.
- `GetDriver` query adds `icon`, `description` and `links { label url }`.
- `FilteredDriver` (`frontend/src/pages/drivers/lib/driverList.ts`) gains `latestVersion: DriverListVersion | undefined`, computed from all versions before filtering (the same set `latestVersionId` uses).

## Relationships

```text
ApplicationDriver 1 ──< ApplicationDriverVersion
                         ├─ icon         (0..1 URL)
                         ├─ description  (0..1 text)
                         └─ links        (0..n {label, url}, ordered)
```

The list header for an `ApplicationDriver` reads these from its latest-wins `ApplicationDriverVersion`; the detail page reads them from the selected version.
