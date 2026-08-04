# Extraction Record

**Extracted on**: 2026-08-04
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. This is a config-only application driver that reuses established machinery; every
research entry is a confirmation against existing code or a placement decision, not an
architectural choice.

## Knowledge Updated

- `dev/knowledge/backend/services.md` (Driver Models — **new subsection** "Parameter
  declarations: requiredness and kinds", from R2 and R4)

Two conventions that surprise driver authors, and that `driver/DRIVERS.md` documents
neither of:

1. **A parameter is required iff it has no `default`.** There is no `required` field on
   `DriverParameterDefinition`; `validate_parameter_values` treats a default-less
   parameter as mandatory. Because the model is `extra="forbid"`, writing
   `required: true` fails driver-load validation rather than adding a constraint.
2. **`DriverParameterKind` is `string | integer | boolean | enum` — there is no `secret`
   kind.** Credentials must not be parameters. Values that must not vary belong as
   literals in `values.j2.yml`, not as parameters with a default.

## Guidelines Updated

None.

## Not extracted

- R1 (which reference driver to copy), R5/R6 (OCI chart coordinates, `appVersion`, pod
  selector label, and values key paths — all verified against the published
  `infrahub-mcp` `0.1.0` chart on 2026-06-21; a point-in-time confirmation, not durable
  guidance), R3 (enum parameter schema, now covered by the knowledge subsection above),
  R7 (unit-test approach as the owner-approved E2E substitute), R8 (docs-catalogue
  placement in `driver/DRIVERS.md` and `docs/docs/drivers/loading-drivers.md`).

## Suggested adjacent follow-up

`driver/DRIVERS.md` documents the `parameters` block without stating either convention
above. Adding two lines there would put the facts where driver authors actually look;
outside this extraction's scope (`driver/` is not part of the `dev/` documentation
system).

## Archive

Spec directory moved to `specs/archive/015-infrahub-mcp-driver/` as a historical record.
