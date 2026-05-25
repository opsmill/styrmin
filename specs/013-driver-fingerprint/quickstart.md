# Quickstart: Driver Reload Identity — Provenance Fingerprint

**Phase**: 1 (Design & Contracts)
**Purpose**: end-to-end manual verification of the user-visible behaviour after this feature ships. This is a smoke-test recipe, not a test specification.

## Prerequisites

- Local Styrmin dev stack running: `uv run invoke dev`
- A local copy of an application driver directory (e.g. `driver/infrahub/`) with at minimum: `driver.styrmin.yml`, a values template file, and `actions.py` if `spec.actions` is non-empty.

## Step 1 — Load the driver

```bash
styrminctl driver load ./driver/infrahub/
styrminctl driver list
```

**Expected**: one application driver version row is shown for `infrahub`. The label includes the new suffix:

```
infrahub  1.0.0@a1b2c3d   local
```

## Step 2 — Reload with no changes (idempotency)

```bash
styrminctl driver load ./driver/infrahub/
styrminctl driver list
```

**Expected**: same row count as Step 1 (still one row). The fingerprint suffix is identical. No error, no warning, no new row.

## Step 3 — Edit and reload (drift detection)

Edit `driver/infrahub/templates/values.yml.j2` (or whichever file is the values template) to add a `commonLabels:` entry — any meaningful or trivial edit will do. Do NOT bump `version` in `driver.styrmin.yml`.

```bash
styrminctl driver load ./driver/infrahub/
styrminctl driver list
```

**Expected**: two rows for `infrahub` are now shown, both with the same `version` string but different short fingerprints:

```
infrahub  1.0.0@a1b2c3d   local
infrahub  1.0.0@e9f0a1b   local
```

## Step 4 — Confirm cascade fix (no IntegrityError on reload)

Repeat Step 3 multiple times with mixed edits to any of the three hashed files (`driver.styrmin.yml`, the values template, `actions.py`). Every reload completes without error. Edits to non-hashed files (`README.md`, screenshots) MUST NOT produce new rows.

## Step 5 — Inspect detail surface (full fingerprint)

Open the frontend (`http://localhost:5173/` or however the dev stack exposes it). Navigate to **Drivers → infrahub → Versions**. Click any version row.

**Expected**: the detail surface shows the version string, the full `content_hash` (64 hex characters), and a copy button that places the full hash on the clipboard. The version-list summary on the parent page already shows the short suffix.

## Step 6 — Verify GraphQL surface

```bash
gql query <<'EOF'
{
  applicationDrivers {
    name
    versions {
      version
      contentHash
      sourceCommitSha
      sourceType
    }
  }
}
EOF
```

**Expected**: each `ApplicationDriverVersion` object includes `contentHash` (populated for `sourceType == "local"`, null otherwise) and `sourceCommitSha` (populated for `sourceType == "git"`, null otherwise).

## Step 7 — Verify the git path (optional, requires a reachable repo)

Load a driver from a git repository:

```bash
styrminctl driver load --git https://example.com/your-driver.git --branch main
```

**Expected**: one row appears with the suffix `@<short-commit-sha>`. Push a new commit on the branch, then reload — a second row appears with the new short SHA.

## Step 8 — Verify documentation

- [ ] `CONTEXT.md` "Provenance fingerprint" entry is present and accurate.
- [ ] `dev/guides/driver-iteration.md` exists and describes the iteration loop without requiring `version` bumps, the three-file hash input, and the row-accumulation behaviour.
- [ ] Any `docs/` site page that describes driver loading mentions the fingerprint suffix in display examples.

## What's NOT in scope for this quickstart

- Pruning unused application driver version rows (filed as a follow-up).
- Hash recomputation for legacy NULL rows in a dev DB (developers either drop-and-recreate or accept one-time row duplication).
