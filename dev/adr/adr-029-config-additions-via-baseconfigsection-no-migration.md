# ADR-029: Config additions ride through `BaseConfigSection` and existing JSON columns

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-external-dns-endpoints-type/research.md (D1, D3)

## Context

Adding a new operator-tunable config knob (the trigger for this ADR was `external_dns_endpoints_type` for IPv6/dual-stack clusters, but the question is general) raises two recurring questions:

1. **Where does the field live in the Pydantic config hierarchy?**
2. **Does it need DB migration or GraphQL schema changes to ship?**

The config hierarchy is:

```text
BaseConfigSection
├── ClusterConfig
├── EnvironmentConfig
└── DeploymentConfig (multi-inherits from ClusterConfig + EnvironmentConfig)
    └── ResolvedConfig (output of the Cluster → Environment → Deployment merge)
```

The merge (`_resolve_instance_config` in `context/resolvers.py`) uses generic `**model_dump(exclude_none=True)` dict-spread with deepest-wins precedence. The DB columns `Cluster.config`, `Environment.config`, and `Deployment.config` are typed `JSON`. The GraphQL mutations `create_cluster` / `create_environment` / `create_deployment` accept `config: JSON | None`.

This means **for any new field that should be settable at any layer and merged deepest-wins, the entire plumbing already exists** — adding it to the Pydantic models is the only code change.

## Decision

The default pattern for a new operator-tunable config field is:

1. **Add the field to `BaseConfigSection`** in `context/models/config.py`, with an `Optional` type and a `None` default. The shared parent class means every layer (`ClusterConfig`, `EnvironmentConfig`, `DeploymentConfig`, transitively `ResolvedConfig`) accepts the field with zero per-layer plumbing.
2. **Use Pydantic-native validation** (`Literal[...]`, constrained ints, custom validators) so rejection happens at config-parse time, with errors that name the offending field. The inherited `model_config = ConfigDict(extra="forbid")` catches misspelled keys.
3. **Make no changes to**:
   - `backend/styrmin_backend/db/models.py` — the `config` columns are already `JSON`/`JSONB` and round-trip arbitrary keys.
   - `schema.graphql` and the SDK Pydantic types — the mutations already accept `config: JSON | None`; the new key becomes a recognized member of that blob, validated server-side at deserialization.

Storage and wire surfaces remain identical; the only artifact that changed is the Pydantic class. Existing rows whose `config` blob omits the key deserialize to `field=None` by default — the new feature is a no-op for them.

This pattern explicitly **avoids triggering the Constitution's Governance Gates** (DB schema changes, GraphQL schema modifications) for additive operator-config work.

## When this pattern does NOT apply

- The field needs to be queried/filtered by the database (`WHERE config_xxx = ...`) — JSON-blob storage makes that vendor-specific and slow. Promote to a typed column.
- The field needs to be a typed input on a non-`config` mutation (e.g., a typed update surface like `UpdateDeploymentInput` per [[adr-018-typed-update-deployment-input]]) — that path *does* require GraphQL schema work, by design.
- The field needs a strongly-typed GraphQL output type so the frontend can drive UI off introspection — JSON scalar hides the structure.

In those cases, take the governance hit and do the migration / schema work. The point of this ADR is that for *most* operator-tunable knobs, you don't have to.

## Consequences

- Adding a config knob is a one-file change — fast, low-risk, and operationally cheap (operators upgrading get the new key accepted without any data preparation).
- The pattern composes: `external_dns_endpoints_type` (this spec), and every prior field that lives on `BaseConfigSection` (`ingress_class`, `fqdn_suffix`, `external_url_scheme`, `external_url_port`, `db_size`, `scheduling`) all use the same recipe.
- The wire surface stays loose-typed JSON, which means clients have no compile-time visibility into the new field. Acceptable because the SDK and UI re-derive shape from the Pydantic models, not from GraphQL introspection.
- Layer precedence (deepest wins) propagates the new field automatically: cluster value → environment value (if set) → deployment value (if set). No merge code changes.
- Pydantic-native validation produces actionable errors at config-parse time, satisfying the "fail fast, fail clearly" expectation without custom validators.

## Alternatives Considered

- **Place the field only on `ClusterConfig`**: rejected as the *general* pattern. Some fields genuinely belong on only one layer, but the default should be `BaseConfigSection` because operators routinely need per-environment or per-deployment overrides.
- **Introduce a sub-model (e.g., `ExternalDnsConfig`) per future feature**: rejected as premature abstraction. Flat fields on `BaseConfigSection` match the precedent and stay flat until there are at least 2–3 related knobs to group.
- **Promote every new field to a typed GraphQL input**: rejected as the default. It would mean every config knob triggers the GraphQL governance gate and SDK regeneration; aside from the workflow cost, it hides the fact that config payloads are loose-typed end-to-end and that the Pydantic models are the actual source of truth.
