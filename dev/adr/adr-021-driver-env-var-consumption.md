# ADR-021: Driver-Side Env Var Consumption via Values Template

**Status**: Proposed
**Date**: 2026-05-08
**Source**: specs/010-driver-env-var-consumption/ (spec, plan, research)
**Supersedes**: the post-render env-vars injection portions of [ADR-019](adr-019-deployment-env-vars.md) (§3 conflict policy + the `EnvVarsPatch` / `envVarCollisions` surfaces); ADR-020's environment-config fanout is unaffected.

## Context

Stub — content lands in T030. Will explain why post-render env-vars injection failed (k8s strategic-merge has no container wildcard; per-container patches require chart-internal container names the platform doesn't have without an invasive new contract) and why driver-side consumption is the right boundary.

## Decision

Stub — content lands in T030. Will record the six load-bearing decisions: (1) why post-render injection failed, (2) why driver-side consumption is the right boundary, (3) why merged dicts (not layered) in v1, (4) why no helper macros in v1, (5) migration responsibility lies with driver authors, (6) relationship to ADR-019 + ADR-020.

## Consequences

Stub — content lands in T030. Will enumerate easier/harder/convention-to-replicate consequences of pivoting from platform-side injection to driver-side consumption, and what driver authors must do on upgrade.
