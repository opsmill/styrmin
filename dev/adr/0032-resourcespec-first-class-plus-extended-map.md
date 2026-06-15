# ADR-032: `ResourceSpec` — first-class CPU / memory / ephemeral-storage + `extended` map for the long tail

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-pod-scheduling-config/research.md (Decision 3)

## Context

Pod scheduling needs to carry resource `requests` and `limits` through the same Cluster → Environment → Deployment → Component merge as other scheduling knobs. The Kubernetes resource model is fundamentally open-ended: alongside CPU and memory, pods can request `ephemeral-storage`, several `hugepages-*` variants, GPU resources like `nvidia.com/gpu`, and any number of vendor-defined extended resources that are valid Kubernetes resource names but unknown ahead of time.

A typed Pydantic model has to balance two pressures:

- The **common case** (CPU + memory, occasionally ephemeral-storage) should be typed strongly: editors should autocomplete `requests.cpu`, validators should reject obvious mistakes, and the merge logic should know what fields exist.
- The **long tail** (hugepages, GPUs, future extended resources) cannot be enumerated up front. Any closed list would require a Pydantic-model change to track a new Kubernetes feature.

## Decision

`ResourceSpec` has two parallel sub-objects, `requests` and `limits`, each with the same shape:

```python
class ResourceQuantitySet(BaseModel):
    cpu: str | None = None                # first-class
    memory: str | None = None             # first-class
    ephemeral_storage: str | None = None  # first-class
    extended: dict[str, str] = {}         # long tail — opaque keys, validated quantities
```

CPU, memory, and ephemeral-storage are **first-class fields**. Editors autocomplete them, the merge logic knows them, and per-field validators run on each.

Everything else (hugepages-* variants, `nvidia.com/gpu`, vendor extended resources) goes into the `extended: dict[str, str]` map. Keys are opaque; values are validated as parseable Kubernetes quantities via a shared `_validate_quantity()` helper. No first-class per-resource semantics are implied.

## Consequences

- The 95% case (CPU + memory) is strongly typed with no escape into stringly-typed config.
- Forward compatibility with future Kubernetes extended resources is automatic — any vendor adding a new resource name can be expressed via `extended` without a platform release.
- Validation guarantees what it can (quantity syntax) and stays out of what it cannot (resource semantics). A miss-typed `nvidia.com/qpu` is still caught as a non-existent resource at scheduling time, but the platform doesn't pretend to know GPUs are scarce.
- The shape is symmetric between `requests` and `limits`, which the merge logic exploits — the same merge rules apply to either side, parameterised by the path.
- The cost: there are two ways to express the same resource (`requests.cpu = "100m"` vs `requests.extended["cpu"] = "100m"`). The Pydantic model rejects duplicates by raising on `extended["cpu"]` if it would collide with the first-class field — disambiguation lives in validation, not in convention.

## Alternatives Considered

- **Single flat `resources: dict[str, dict[str, str]]` map with no first-class fields**: rejected. Loses editor autocompletion and per-field validation for the case that matters most. CPU and memory account for nearly all real configurations; treating them like vendor extended resources is the wrong default.
- **Expand the first-class list to include hugepages variants**: rejected. Hugepages have several named variants (`hugepages-2Mi`, `hugepages-1Gi`, …) that already suit the opaque-key map shape — typing them out would just be a longer enumeration that still doesn't cover all sizes.
- **Closed enum of accepted extended resource names**: rejected. Defeats the whole point of the `extended` map (forward compatibility). Operators would have to ship a platform release to use a new vendor resource.
