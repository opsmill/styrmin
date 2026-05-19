# Quickstart: Automated Daily Release Pipeline

## How It Works

The release pipeline runs daily at midnight UTC. It checks for new commits on `develop`, bumps the patch version, and publishes all artifacts:

```text
Schedule (00:00 UTC)
  │
  ├─ Check for new commits since last v* tag
  │   └─ No changes? → Skip (no release created)
  │
  ├─ Bump patch version (0.1.0 → 0.1.1)
  │   ├─ Update pyproject.toml
  │   ├─ Update helm/styrmin/Chart.yaml
  │   └─ Update helm/agent/Chart.yaml
  │
  ├─ Commit, tag (v0.1.1), push
  │
  ├─ Create GitHub Release (auto-generated notes)
  │
  ├─ Build & push Docker image (signed with cosign)
  │   └─ Tags: 0.1.1, <sha>, latest
  │
  └─ Publish Helm charts (agent first, then styrmin)
      └─ OCI registry: oci://<HARBOR_HOST>/opsmill/chart
```

## Manual Triggers

### Trigger a release manually

Go to **Actions → Release → Run workflow** and click "Run workflow". Optionally enable `dry_run` to test without pushing artifacts.

### Trigger only Docker image publishing

Go to **Actions → Publish Docker Image → Run workflow**, provide a tag or branch.

### Trigger only Helm chart publishing

Go to **Actions → Publish Helm Chart → Run workflow**, select chart name (`styrmin` or `agent`).

## Version Control

### Automated (daily)

Only the **patch** version is incremented automatically: `0.1.0 → 0.1.1 → 0.1.2 → ...`

### Manual (human-initiated)

To bump **minor** or **major** version:

1. Edit `pyproject.toml` and set the new version (e.g., `0.2.0` or `1.0.0`)
2. Commit and merge to `develop`
3. The next daily release will increment from your new base: `0.2.0 → 0.2.1`

> **Do not** manually edit Helm `Chart.yaml` versions — the release workflow synchronizes them automatically.

## Verifying a Release

### Check the GitHub Release

Navigate to the repository's **Releases** page. Each release has auto-generated notes listing PRs since the last release.

### Verify Docker image signature

```bash
cosign verify \
  --certificate-identity-regexp "https://github.com/opsmill/styrmin/.github/workflows/.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  <HARBOR_HOST>/opsmill/styrmin:<version>
```

### Check Helm chart in registry

```bash
helm show chart oci://<HARBOR_HOST>/opsmill/chart/styrmin --version <version>
helm show chart oci://<HARBOR_HOST>/opsmill/chart/styrmin-agent --version <version>
```

## Failure Handling

If Docker or Helm publishing fails after the tag is created:

1. The GitHub Release is automatically marked as **draft**
2. Fix the issue (e.g., registry credentials, Dockerfile error)
3. Re-run the failed job via **Actions → failed workflow run → Re-run failed jobs**
4. Or manually trigger the specific publish workflow with the tag

## Prerequisites

The following GitHub secrets/variables must be configured:

| Name | Type | Purpose |
|------|------|---------|
| `HARBOR_USERNAME` | Secret | Harbor registry username |
| `HARBOR_PASSWORD` | Secret | Harbor registry password |
| `HARBOR_HOST` | Variable | Harbor registry hostname |

These are already configured if Helm chart publishing works today.
