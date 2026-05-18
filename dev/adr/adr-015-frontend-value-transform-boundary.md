# ADR-015: Frontend Value-Transform Layer at the GraphQL Submit Boundary

**Status**: Accepted
**Date**: 2026-05-10
**Source**: specs/archive/011-env-config-input-hardening/ (research §5, spec.md US2)

## Context

Spec 009 introduced full-replacement typed inputs (e.g. `UpdateEnvironmentInput`)
to environment-config writes. The frontend's `EnvironmentConfigurationTab`
builds the input from the **persisted** config — read from the GraphQL query
result — and submits it on every env-vars save.

Persisted config is a Pydantic model dump: enums round-trip as **raw strings**
(`"https"`, `"NodeExternalIP"`). GraphQL inputs require **enum literals**
(`HTTPS`, `NODE_EXTERNAL_IP`). The frontend's `buildFullReplacementInput`
helper initially used TypeScript-only `as` casts to bridge the two — which
the compiler accepted but the GraphQL server rejected (or, worse, silently
accepted a mismatched value, depending on the field).

The result was a class of data-loss/silent-corruption bug discovered in
spec 011: opening the Configuration tab on any environment with these enum
fields set and saving env vars either failed validation or quietly
overwrote the persisted enum with the wrong value.

The class of bug is structural: any time a frontend form submits a
full-replacement input built from previously-persisted state, every field
whose persisted shape differs from its GraphQL input shape is a candidate
for silent corruption.

## Decision

Forms that submit a typed GraphQL input built from persisted JSON state
MUST transform raw string enums into GraphQL enum literals at the
**submit boundary** (`buildFullReplacementInput`), using explicit
declarative mapping tables. Unrecognised values throw before submission
rather than submitting `null` or a casted string.

```typescript
const EXTERNAL_URL_SCHEME_MAP: Record<string, ExternalUrlScheme> = {
    "http": ExternalUrlScheme.HTTP,
    "https": ExternalUrlScheme.HTTPS,
};

const EXTERNAL_DNS_ENDPOINTS_TYPE_MAP: Record<string, ExternalDnsEndpointsType> = {
    "NodeExternalIP": ExternalDnsEndpointsType.NODE_EXTERNAL_IP,
    "ClusterIP": ExternalDnsEndpointsType.CLUSTER_IP,
};

function transformEnumValue<E extends string>(
    field: string,
    value: unknown,
    mapping: Record<string, E>,
): E | null {
    if (value == null) return null;
    if (typeof value !== "string") {
        throw new Error(
            `Field ${field}: expected string, got ${typeof value}`,
        );
    }
    const transformed = mapping[value];
    if (transformed === undefined) {
        throw new Error(
            `Field ${field}: unrecognised value "${value}". Expected one of: ` +
            Object.keys(mapping).join(", "),
        );
    }
    return transformed;
}
```

The transform is called for each enum field inside `buildFullReplacementInput`:

```typescript
externalUrlScheme: transformEnumValue(
    "externalUrlScheme",
    config.external_url_scheme,
    EXTERNAL_URL_SCHEME_MAP,
),
```

The form's existing error-display path catches the throw and surfaces an
actionable message to the operator instead of submitting corrupt data.

## Consequences

- Saving env vars on any environment with these enum fields set works
  correctly: the persisted enum survives the round-trip.
- Unrecognised values (corrupt data, future-added enum values not yet in
  the frontend's union) raise a clear error before submission. Operators
  see the field name and the unexpected value; silent corruption is
  impossible by construction.
- TypeScript-only `as` casts are explicitly forbidden at this boundary.
  The compiler does not see the persisted-to-GraphQL gap, so the human
  must.
- The mappings are **declarative tables** maintained next to the form,
  matched by hand to the Pydantic source of truth. When new enum values
  land on the Pydantic side, both the form's union and the mapping table
  must be updated — a deliberate friction point that makes the boundary
  explicit.
- The pattern generalises beyond enums: any persisted-shape vs
  GraphQL-shape divergence (date strings, partial objects, JSON-encoded
  payloads) belongs at this same boundary with the same throw-on-unknown
  discipline.
- Read-direction (GraphQL → display) does not need the same transform
  layer for these enum fields — the form reads the persisted JSON config
  directly, so the read path is the identity transform.

## Alternatives Considered

- **TypeScript `as` casts**: this was the original implementation; it
  silently accepts mismatched runtime shapes. Compiler-level type safety
  is not runtime safety; rejected.
- **Codegen-generated mapping tables**: rejected — adds codegen complexity
  for a handful of two-to-four-entry mappings. Manually maintained tables
  are clearer and surface drift at code-review time.
- **Try/catch around the throw and submit anyway with `null`**: rejected —
  silent corruption is exactly the bug being fixed.
- **Validate on the backend and return a typed error**: a defence-in-depth
  measure that already exists (the GraphQL layer rejects unknown enum
  values), but it surfaces the error after a network round-trip and
  conflates "operator typed something wrong" with "the form's mapping is
  stale". Catching at the form is the cheaper, more actionable layer;
  backend validation remains as the second line.
