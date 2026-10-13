# GraphQL Contract: Driver Logo, Description and Links

Additive, read-only change. No new query, mutation, argument or input type. Existing mutations `loadApplicationDriverVersion` and `loadLocalApplicationDriverVersion` return `ApplicationDriverVersion`, so they expose the new fields too.

## Schema diff (`schema.graphql`)

```graphql
type ApplicationDriverVersion {
  # ...existing fields unchanged...

  """
  URL of the driver's logo image, from `spec.info.icon` in the driver
  specification file. An absolute http or https URL; the browser of each
  viewer loads the image from it. Null when the driver does not set it.
  """
  icon: String

  """
  Description of the application, from `spec.info.description`. Null when
  the driver does not set it.
  """
  description: String

  """
  Links from `spec.info.links`, in file order. Empty when the driver does not
  set any.
  """
  links: [DriverLink!]!
}

"""
A link a driver declares under `spec.info.links`, such as its homepage or
documentation.
"""
type DriverLink {
  """Link text, from the `link` key of the entry."""
  label: String!

  """Absolute http or https URL, from the `url` key of the entry."""
  url: String!
}
```

## Example query

```graphql
query GetDriverInfo($applicationDriverId: UUID!) {
  applicationDriver(applicationDriverId: $applicationDriverId) {
    versions {
      id
      icon
      description
      links { label url }
    }
  }
}
```

Response for the `infrahub` example driver:

```json
{
  "icon": "https://docs.infrahub.app/img/infrahub-logo.svg",
  "description": "Next generation source of truth for infrastructure management",
  "links": [
    { "label": "Homepage", "url": "https://www.opsmill.com/" },
    { "label": "Documentation", "url": "https://docs.infrahub.app/" },
    { "label": "Github", "url": "https://github.com/opsmill/infrahub" }
  ]
}
```

URLs are returned as `HttpUrl` normalizes them (for example, a trailing `/` is added to a bare host).

Response for a driver version without `spec.info`, or stored before this change and not reloaded:

```json
{ "icon": null, "description": null, "links": [] }
```

## Load errors

Loading a driver with an invalid value fails with the existing error path (`DriverLoadingError` → GraphQL error). The message contains `The driver specification is invalid:` and the Pydantic location of the bad field, for example:

- `spec.info.icon` — `xxxx`, `logo.svg`, `javascript:alert(1)`, `data:image/png;base64,...`
- `spec.info.links.0.url` — a URL that is not http or https
- `spec.info.links.1.name` — an extra key (`Extra inputs are not permitted`)

## Propagation tests (Constitution §V)

| Field | Test | Direction |
|-------|------|-----------|
| `icon`, `description`, `links` | load a local driver → DB row → `applicationDriver.versions` | write + read |
| same | seed a row with NULL info → reload same identity → same `id` carries the values | write (backfill) + read |
| same | seed a row with NULL info → read | read (`null`, `null`, `[]`) |

## SDK / CLI

`schema.graphql` and the SDK's generated schema types are regenerated. No SDK `.graphql` operation adds the fields, so SDK method return models and CLI output do not change.
