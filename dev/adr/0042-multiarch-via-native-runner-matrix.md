# ADR-042: Multi-arch Docker builds via native-runner matrix + manifest merge (no QEMU)

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/003-automated-release/research.md (R10)

## Context

The release pipeline publishes Docker images for both `linux/amd64` and `linux/arm64`. Two build strategies exist:

1. **QEMU emulation on a single x86 runner** — `docker/setup-qemu-action` + `docker buildx build --platform linux/amd64,linux/arm64`. One job, one runner. The arm64 binary runs through user-mode emulation on x86, which is 5–10× slower than native.
2. **Per-architecture native builds + manifest merge** — a matrix of two jobs, one on `ubuntu-24.04` (amd64), one on `ubuntu-24.04-arm64` (arm64). Each pushes an image **by digest only** (no tag). A third merge job stitches the per-arch digests into a multi-arch manifest list, then a signing job ([[0040-cosign-keyless-image-signing]]) signs the manifest digest.

GitHub now provides hosted arm64 runners (`ubuntu-24.04-arm64`) suitable for native ARM builds. With a daily release target under 15 minutes (SC-002), the emulation tax is not affordable.

## Decision

Build multi-arch images with a **native-runner matrix + manifest merge** pipeline:

1. **`build` job** with `matrix: { include: [{platform: linux/amd64, runner: ubuntu-24.04}, {platform: linux/arm64, runner: ubuntu-24.04-arm64}] }`. Each matrix leg:
   - Runs on its matching native hardware (`runs-on: ${{ matrix.runner }}`).
   - Uses `docker/build-push-action@v7` with `outputs: type=image,name=...,push-by-digest=true`.
   - Pushes the image **by digest only** — no tag at this stage.
   - Uses GHA cache scoped per-platform: `cache-from`/`cache-to` use `scope=${{ matrix.platform }}` to prevent cross-arch cache pollution.
   - Uploads its digest to a GitHub Actions artifact for the merge job.

2. **`merge` job** depends on both matrix legs:
   - Downloads the per-arch digests.
   - Computes tags **once** via `docker/metadata-action` (version tag, git SHA, `latest`).
   - Runs `docker buildx imagetools create --tag <tag1> --tag <tag2> ... <digest1> <digest2>` to produce the manifest list.
   - Exports the manifest-list digest for the sign job.

3. **`sign` job** depends on `merge`:
   - Runs cosign keyless against the **manifest-list digest**, not the per-arch digests (see [[0040-cosign-keyless-image-signing]]).

## Consequences

- **Native speed**: each arch builds on matching hardware. arm64 builds drop from ~10 minutes (QEMU) to ~2 minutes, well within the 15-minute daily-release SLO.
- **Parallelism**: the two arch builds run concurrently on separate runners; wall-clock cost is `max(amd64_build, arm64_build) + merge + sign`, not the sum.
- **Tag race protection**: per-arch pushes are by digest only — no tags applied until the manifest list is created. There is no window where someone could pull `image:1.2.3` and get a partial/per-arch result.
- **Cache cleanliness**: per-platform cache scope means amd64 build cache misses don't pollute arm64's cache or vice versa. Each arch's cache layer chain is self-consistent.
- **Single signature for both arches**: cosign signs the manifest list, which transitively covers both per-arch images. Consumers verify one digest and get both architectures.
- **YAML cost**: a matrix strategy keeps the build job DRY (one job definition, two legs). The merge and sign jobs are added on top. Total: three jobs (build×2 + merge + sign) instead of one — acceptable for the speedup.
- **Hosted-arm64 dependency**: this design assumes GitHub continues to provide arm64 runners. If they go away or become metered differently, the fallback is QEMU + extended timeout — a one-line `runs-on` change.

## Alternatives Considered

- **QEMU emulation** (`docker/setup-qemu-action` + `docker buildx build --platform linux/amd64,linux/arm64`): rejected. arm64 builds run 5–10× slower than native; the daily-release SLO becomes unmeetable on any non-trivial change. Also produces less reproducible builds when emulation imperfections surface in compiled artifacts.
- **Single multi-platform `buildx build`** without QEMU and without an arm64 runner: not actually possible — `buildx` needs **some** way to execute arm64 instructions; either native or emulated.
- **Separate workflows per arch** (one `docker-publish-amd64.yml`, one `docker-publish-arm64.yml`, one orchestrator): rejected. Unnecessary file proliferation; matrix strategy achieves the same parallelism with one workflow.
- **Per-arch tags** (`image:1.2.3-amd64`, `image:1.2.3-arm64`) without a manifest list: rejected. Forces consumers to know about per-arch tags and pick the right one; `docker pull image:1.2.3` should resolve transparently regardless of host architecture, which is what the manifest list enables.
- **Sign each per-arch digest separately**: rejected. See [[0040-cosign-keyless-image-signing]] — the manifest list is the unit consumers pull, so it is the unit that should be signed.
- **Shared cache scope across arches**: rejected. Cache layers from one arch's build are useless to the other (compiled binaries differ); using one shared scope would just produce cache thrash.
