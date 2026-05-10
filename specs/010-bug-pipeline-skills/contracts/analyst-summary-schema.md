# Contract: Analyst Summary Block Schema

The **analyst summary block** is the machine-readable contract between the `bug-analyze` stage (producer) and the `bug-fix` stage (primary consumer). It is also embedded verbatim in the `bug-fix` PR description's `<details>` block, and may be referenced by the `bug-test` stage when deriving reproduction-aligned tests.

## Format

A fenced YAML code block, immediately wrapped by HTML comment markers that downstream stages use as deterministic anchors:

```markdown
<!-- bug-pipeline:summary:start -->

```yaml
schema_version: 1
issue:
  number: 206
  url: https://github.com/opsmill/styrmin/issues/206
hypothesis: |
  One paragraph describing the suspected root cause in plain language. May span
  multiple lines using YAML block-literal syntax.
affected_files:
  - backend/styrmin_backend/api/schema/cluster.py
  - backend/styrmin_backend/services/cluster.py
reproduction:
  - "Apply the manifest from the issue's reproduction section"
  - "Run `kubectl get pods -n styrmin-test`"
  - "Observe that the pod is stuck in CrashLoopBackOff"
short_description: cluster-pod-crashloop-on-empty-spec
next_command: /bug-fix 206
```

<!-- bug-pipeline:summary:end -->
```

## Field reference

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `schema_version` | integer | yes | Currently `1`. Consumers MUST refuse to parse if missing or unexpected. |
| `issue.number` | integer | yes | Positive. Matches the issue the comment is posted on. |
| `issue.url` | string | yes | Canonical GitHub URL. |
| `hypothesis` | string | yes | Plain-language root-cause hypothesis. ≥ 1 sentence; ≤ ~500 chars. May use YAML block-literal (`\|`) for multi-line. |
| `affected_files` | list of strings | yes | Repo-relative paths. May be empty (`[]`) if localisation failed; the fix stage MAY treat empty as a soft signal to widen its search. |
| `reproduction` | list of strings | yes | At least 1 step. Each step is a single-line shell command, action description, or expected observation. |
| `short_description` | string | yes | Kebab-case fragment for the fix-branch name. `^[a-z0-9][a-z0-9-]{0,39}$`. |
| `next_command` | string | yes on success, **omitted on failure** | Slash command including argument, e.g. `/bug-fix 206`. Absent indicates failure mode (see FR-007). |

## Producer rules (analyze stage)

- The block MUST be the **last** structured element in the analyst's comment, after all prose sections.
- The HTML comment markers `<!-- bug-pipeline:summary:start -->` and `<!-- bug-pipeline:summary:end -->` MUST be present on their own lines, exactly as shown.
- The fenced block MUST use the `yaml` language tag for syntax highlighting in the GitHub UI.
- On failure paths (analysis cannot produce a hypothesis), the producer MUST omit the entire block — no empty/placeholder block is acceptable. The failure comment is prose-only and contains no `next_command`.

## Consumer rules (fix / test / review)

- Locate the **most recent** comment on the target issue containing both markers.
- Extract the YAML between the markers and parse it.
- Reject the comment if `schema_version != 1` and post a failure comment naming the version mismatch.
- Treat any field violation (missing required field, type mismatch, regex failure) as a parse failure and surface a clear error message — do **not** silently fall back to fuzzy matching.

## Versioning

- v1 (this document) is the initial contract.
- Future versions bump `schema_version` and add a parallel reference here. Producers and consumers in the same PR are kept in lock-step; a producer at v2 must not coexist on `develop` with consumers still expecting v1 unless the v2 schema is a strict superset.
