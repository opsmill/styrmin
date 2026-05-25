# Contract: GraphQL schema delta — `ApplicationDriverVersion` fingerprint fields

**Phase**: 1 (Design & Contracts)
**Surface**: GraphQL boundary (`backend/styrmin_backend/api/definitions/application_driver/model.py`)
**Generates**: `schema.graphql` + SDK types (`python_sdk/src/styrmin_sdk/graphql/_generated/`)

## Field additions

Two new read-only scalar fields on the `ApplicationDriverVersion` type.

```graphql
type ApplicationDriverVersion {
  # … existing fields unchanged …

  """
  SHA-256 hex (64 chars) of the canonical three-file input
  (driver.styrmin.yml + values template + actions.py when present),
  populated when sourceType == "local".
  Null when sourceType != "local".
  """
  contentHash: String

  """
  Git commit SHA (40 hex chars) resolved at load time from the source
  repository's HEAD on the loaded branch,
  populated when sourceType == "git".
  Null when sourceType != "git".
  """
  sourceCommitSha: String
}
```

Strawberry camelCases by default, so Python field names `content_hash` and `source_commit_sha` surface as `contentHash` and `sourceCommitSha` in the schema. This matches the project's existing convention (`sourceType`, `sourceRepository`, etc.).

Strawberry mapping in `model.py:104-194`:

```python
@strawberry.type
class ApplicationDriverVersion:
    # … existing fields …
    content_hash: str | None = None
    source_commit_sha: str | None = None

    # `from_instance` populates the new fields from the SQLModel row:
    @classmethod
    def from_instance(cls, instance: ApplicationDriverVersionModel) -> ApplicationDriverVersion:
        return cls(
            # … existing kwargs …
            content_hash=instance.content_hash,
            source_commit_sha=instance.source_commit_sha,
            instance=instance,
        )
```

## Mutations

None. No new mutation is added by this feature. The fingerprint is populated as a side effect of the existing `loadApplicationDriverFromLocalDirectory` and `loadApplicationDriverFromGitRepository` mutations (or whatever the current mutation names are in the schema — load paths are unchanged at the GraphQL surface).

## Propagation tests (mandatory per Constitution §V)

Two propagation tests required, both following the recipe in `dev/guides/graphql-propagation-tests.md`:

1. **`contentHash` read propagation**:
   - Seed an `ApplicationDriverVersion` row with `source_type = "local"`, `content_hash = "<known sha256>"` via the real repository layer.
   - Execute a GraphQL query that selects `applicationDriverVersion { contentHash }` against the real schema.
   - Assert the resolver returns the seeded hex value verbatim.

2. **`sourceCommitSha` read propagation**:
   - Seed an `ApplicationDriverVersion` row with `source_type = "git"`, `source_commit_sha = "<known 40-char SHA>"`.
   - Query `applicationDriverVersion { sourceCommitSha }`.
   - Assert the resolver returns the seeded SHA verbatim.

Both tests should be in `backend/tests/unit/api/schema/test_application_driver_version_propagation.py`.

No new GraphQL inputs are introduced, so the schema-walking input propagation harness (ADR-014) does not apply to this feature.

## SDK contract

The SDK's auto-generated Pydantic types under `python_sdk/src/styrmin_sdk/graphql/_generated/` gain `content_hash: str | None` and `source_commit_sha: str | None` attributes on the `ApplicationDriverVersion` model. This is a non-breaking additive change.

Any `.graphql` files under `python_sdk/src/styrmin_sdk/graphql/` that select `ApplicationDriverVersion` should be updated to include the new fields if downstream callers need them. At minimum, any query whose results feed the CLI's driver-list rendering MUST select both new fields.

Regeneration command (per AGENTS.md):

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
```

Both regenerations MUST be in the same change; CI fails otherwise.

## Backwards compatibility

- Adding two nullable scalar fields is a non-breaking GraphQL change. Existing clients that do not select the new fields are unaffected.
- The two fields are exposed as nullable, matching the model layer's `str | None`. A future feature that enforces "exactly one is non-null" via a DB CHECK constraint will not change the GraphQL nullability — clients must still tolerate null.
