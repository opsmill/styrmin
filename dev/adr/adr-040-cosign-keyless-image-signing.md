# ADR-040: Container image signing — cosign keyless via GitHub OIDC, sign-by-digest, manifest-list scope

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/003-automated-release/research.md (R5, with R10 for the manifest-list detail)

## Context

The automated daily release pipeline pushes multi-arch Docker images to a registry. Consumers (operators installing Styrmin) need a verifiable signal that an image was built by the project's release workflow and not tampered with after publish.

Three signing models were considered:

1. **Key-based cosign signing** — generate a signing key, store the private key as a GitHub secret, rotate periodically.
2. **Keyless cosign signing via OIDC** — no long-lived keys; signatures are issued by Fulcio against a short-lived certificate bound to the GitHub Actions OIDC token, logged to the Rekor public transparency log.
3. **Notation (Notary Project)** — competing standard; less mature GitHub Actions integration than cosign as of this writing.

Tag-vs-digest is a separate axis: signing by `image:tag` has a TOCTOU window (the tag can be re-pointed between signing and verification), while signing by `image@sha256:<digest>` binds the signature to immutable content.

Multi-arch images (built per [[adr-042-multiarch-via-native-runner-matrix]]) are published as a **manifest list** referencing per-architecture image digests. Signing the per-arch digests separately would force consumers to verify each architecture's signature independently and miss the manifest-list integrity check.

## Decision

The release pipeline signs every published image with **cosign keyless via the GitHub Actions OIDC identity**:

- The signing job uses `sigstore/cosign-installer@v4` and requires `id-token: write` on the job permissions.
- Signing is done **by digest**, not by tag: `cosign sign --yes image@sha256:<digest>`. The `--yes` flag suppresses the interactive prompt that cosign would otherwise show in CI.
- The signed digest is the **manifest list digest** (the output of the merge step in [[adr-042-multiarch-via-native-runner-matrix]]), not the per-arch digests. One signature covers the multi-arch manifest, which transitively covers each architecture.
- Rekor upload is on by default in cosign 2.0+ (`COSIGN_EXPERIMENTAL` is deprecated). No flag needed.
- The certificate carries the GitHub Actions workflow identity (`https://github.com/opsmill/styrmin/.github/workflows/<workflow>`) and the OIDC issuer (`https://token.actions.githubusercontent.com`). Consumers verify against those values:

```bash
cosign verify \
  --certificate-identity-regexp "https://github.com/opsmill/styrmin/.github/workflows/.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  IMAGE@DIGEST
```

## Consequences

- **No key management**: there is no private key to store, rotate, or revoke. The signing identity is the GitHub Actions OIDC token, which is ephemeral and re-issued per workflow run.
- **Verifiable provenance**: a consumer can prove a given image was produced by a Styrmin GitHub Actions workflow without trusting any single party — Fulcio's certificate, Rekor's transparency log, and GitHub's OIDC issuer are all independently verifiable.
- **TOCTOU-safe**: signing by digest binds the signature to immutable bytes. Re-tagging an image (`docker tag :latest :rollback`) doesn't move the signature; verification still resolves to the same digest.
- **Manifest-list scope** matches the unit consumers pull. `docker pull image:1.2.3` resolves to the manifest list; verifying that one digest is sufficient. If we signed per-arch digests, consumers would either have to enumerate architectures or risk verifying only one.
- **Rekor transparency** is on by default — every signature is publicly logged, providing append-only audit trail that compromises the signing infrastructure can't quietly rewrite.
- **Operational cost**: the signing job needs `id-token: write` and adds a small step to the release pipeline. The cosign binary install is a one-action step.

## Alternatives Considered

- **Key-based cosign signing**: rejected. Requires generating and storing a signing key as a GitHub secret, plus a rotation discipline nobody wants to own. Keyless OIDC removes the entire key-management surface for the same verification guarantee.
- **Notation (Notary Project)**: rejected. Technically valid but its GitHub Actions integration is less mature than cosign's, and the verification UX is less familiar. Switching is a future option if Notation overtakes cosign in tooling.
- **Sign by tag**: rejected. TOCTOU window: between signing `:1.2.3` and a consumer pulling it, the tag can be re-pointed. Signing by digest eliminates the window structurally.
- **Sign per-arch digests separately**: rejected. Consumers pull the manifest list, not individual arch images. Per-arch signatures would force them to enumerate and verify each architecture, missing the manifest-list-as-a-unit guarantee. The manifest list digest is the right scope.
- **`COSIGN_EXPERIMENTAL=1` env var**: legacy. Deprecated since cosign 2.0 — keyless is default behaviour now.
