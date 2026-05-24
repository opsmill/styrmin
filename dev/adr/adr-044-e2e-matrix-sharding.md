# 044. E2E test parallelism via matrix sharding (not pytest-xdist)

## Status

Accepted, 2026-05-23.

## Context

`backend/tests/e2e/` is the largest contributor to CI wall-clock. Pre-refactor
shape: two monolithic GitHub Actions jobs (`e2e-tests-api`,
`e2e-tests-ui`), each booting one vcluster and running every E2E test
serially in one worker. Target per issue #242: 30%+ wall-clock reduction
on the slower job while preserving the dual-entrypoint contract and the
`--pdb` debugging workflow described in AGENTS.md.

Two viable parallelism approaches:

- **Matrix sharding** — N CI jobs per entrypoint, each with its own
  vcluster. Selected.
- **pytest-xdist with worker-scoped vcluster** — one CI job, N workers
  on one runner each booting their own vcluster. Considered, rejected.

## Decision

Use **GitHub Actions matrix sharding** with 5 shards × 2 entrypoints
(minus exclusions for entirely api_only / ui_only shards). Each cell
boots its own vcluster.

Shards: `general` (readonly + short-mutation tests), `env` (env-vars
+ env-update), `compute` (pod scheduling + ingress controller),
`backup` (Velero / MinIO, isolated), `configuration` (config-drawer
UI flows).

The grouping intentionally targets per-cell wall-clock of 15-20
minutes, matched to the intrinsic floor set by the `configuration`
shard (~25-30 min for the drawer suite). Over-sharding past that
floor traded matrix overhead and Docker network IP-pool contention
(opsmill/styrmin#261) for cells that finished in 5-8 minutes — no
net wall-clock benefit. Routing via bare-name `@pytest.mark.shard_<name>` markers
enforced by a conftest collection hook. Additional shards (e.g. for
the Infrahub app stack) will be added when their tests are written.

## Consequences

### Positive

- `--pdb` workflow unchanged — each shard runs single-threaded.
- Failure attribution is per-shard in the GitHub Actions UI.
- Tuning is YAML-level; re-sharding is a flat edit.
- The existing per-runner `STYRMIN_IMAGE_VER` mechanism already
  prevents cross-shard image collisions on shared self-hosted runners.
- Measured wall-clock reduction: TBD% on the slower entrypoint (fill
  in once the first matrix-enabled CI run on `develop` is available).

### Negative

- ~6× runner-minutes vs. the old 2-job layout. Acceptable on
  `huge-runners`; would not be acceptable on GitHub-hosted runners.
- Re-balance the shards when one becomes the bottleneck (see
  `dev/guides/e2e-parallelism.md`'s "Tuning a slow shard" section).
- Cross-shard fixture coupling now matters; tests cannot rely on
  state created by tests in other shards.

## Rejected alternative: pytest-xdist with worker-scoped vcluster

- Conftest rewrite would convert every `scope="session"` fixture to
  worker-scope, with care for `tmp_path_factory`, port-forward
  collisions, and Helm install collisions.
- 4+ vclusters on one runner = Docker / kubelet / inotify pressure.
  The existing `_portforward` retry loop already exists because of
  port allocation races; xdist multiplies the race surface.
- `--pdb` interaction: xdist traps stdin; AGENTS.md's debugging
  recipe would break unless we documented a "single-worker mode"
  toggle for every debugging session.
- Failure attribution: one interleaved log, N workers' worth of
  `_dump_namespace_logs` from N namespaces.

Reconsider only if matrix sharding hits a runner-cost ceiling.

## References

- Issue: opsmill/styrmin#242
- Spec: `docs/superpowers/specs/2026-05-23-e2e-parallelism-design.md`
- Plan: `docs/superpowers/plans/2026-05-23-e2e-parallelism.md`
- Guide: `dev/guides/e2e-parallelism.md`
- Guide: `dev/guides/e2e-deployment-sharing.md`
