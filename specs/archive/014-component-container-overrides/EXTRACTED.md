# Extraction Record

**Extracted on**: 2026-08-04
**Extracted by**: speckit.opsmill.extract

## Nothing new to extract

This feature documented itself in the same change, as Constitution §VII requires. All
durable content already lives in the documentation system:

| Artefact | Covers |
|---|---|
| [`dev/adr/0045-container-override-no-layering-and-omit-marker.md`](../../../dev/adr/0045-container-override-no-layering-and-omit-marker.md) | D2 (no layering), D5 (per-field typed errors), D8 (the marker design), D4 (validation shape), plus §5 on unguarded charts |
| [`dev/guides/driver-container-override-consumption.md`](../../../dev/guides/driver-container-override-consumption.md) | The Jinja filters, the chart `{{- with }}` guard, the `null`-marker variant, the no-enforcement policy |
| `CONTEXT.md` | The **container override** glossary entry |

## ADRs Created

None.

## Knowledge Updated

None.

## Guidelines Updated

None.

## Worth knowing: ADR-045 is more accurate than this spec's research

`research.md` D8 prescribes an **omit-marker** (filter returns `None`, the template omits
the key when unset). Implementation E2E proved that silently breaks *clearing*: the
operator applies HelmRelease `spec.values` via JSON merge-patch (RFC 7386), where an
omitted key is left **unchanged**, so a cleared override never reached the pod. The
shipped design is the **empty-list marker**, with a `null`-marker variant plus a
create-path `prune_none_on_create` flag for charts that consume the value unguarded.

D8 in this directory carries an inline correction notice, and ADR-045 records the
supersession. **Read the ADR, not the research, for the container-override contract.**

## Not extracted

D1, D3, D6, D7, D9–D15 — faithful ports of the env-vars precedent (008/010, ADR-013) and
of ADR-018/ADR-029/ADR-037, already documented at those decisions.

## Archive

Spec directory moved to `specs/archive/014-component-container-overrides/` as a
historical record.
