# Changelog guide

Styrmin uses [`towncrier`](https://towncrier.readthedocs.io/) for changelog management and generation, with the same configuration and rules as [opsmill/infrahub](https://github.com/opsmill/infrahub).

The changelog is maintained in `CHANGELOG.md` at the repo root. It is **generated** — never edit it by hand. The release workflow owns the section below the `<!-- towncrier release notes start -->` marker, so hand-written entries are either lost or duplicated.

Styrmin follows the best practices from [Keep a Changelog](https://keepachangelog.com/), and our categories of change are:

- **Added** for new features
- **Changed** for changes in existing functionality
- **Deprecated** for soon-to-be removed features
- **Removed** for now removed features
- **Fixed** for any bug fixes
- **Security** in case of vulnerabilities
- **Housekeeping** for internal maintenance and tooling (build, CI, dev scripts) — an OpsMill addition beyond the Keep a Changelog set

## Creating changelog entries

What this means in practice for contributing to Styrmin is:

1. Any PR to `develop` (or `stable`) that changes user-visible behaviour should contain at least one Markdown-formatted "newsfragment" file in the `changelog/` directory. Create it with `towncrier create` rather than by hand — the command reads the config and names and places the file correctly from anywhere in the repo:

    ```bash
    uv run towncrier create -c "Fixed deployments getting stuck in PENDING after an agent restart" 312.fixed.md
    ```

1. The file is named `<github issue id>.<change type>.md`. For example:
   - A newsfragment named `312.fixed.md` represents a bug-fix PR closing GitHub issue #312.
   - This allows `towncrier` to populate the correct section of the changelog with the relevant information.
   - *Note*: if a PR doesn't close (or at least reference) a specific issue, use plain text for the prefix by appending `+` to the filename, for example `+deployments-apply.added.md`.
   - *Note*: use the GitHub issue number, or `+` if there is no GitHub issue — never an internal ticket ID. `towncrier`'s `issue_format` turns the fragment name directly into a GitHub issue URL, so an internal ID ships as a broken link in the changelog.
1. Available newsfragment suffixes are:
   - `added`
   - `changed`
   - `deprecated`
   - `removed`
   - `fixed`
   - `security`
   - `housekeeping`
   - *Note*: dependency-version bumps are recorded as `changed`, not `housekeeping`. Reserve `housekeeping` for tooling, build, and CI maintenance.
1. Write one paragraph, past tense, from the user's perspective — what changed, not how it was implemented. Keep it on a single line; the renderer emits it as one Markdown bullet, so hard-wrapping breaks the list.

    > "Refactored the driver-version resolver to sort by semver" → **"Changed driver-version resolution to be deterministic: the highest `spec.version` wins, with ties broken by load time."**

1. Preview the pending release notes before opening the PR:

    ```bash
    uv run invoke release.draft
    ```

## Release

Releases are automated. The [release workflow](../../.github/workflows/release.yml) runs `towncrier build --yes --version <new-version>` in its `create-release` job, which:

1. Consolidates the newsfragments in `changelog/` into `CHANGELOG.md`, prepending the new release section below the `<!-- towncrier release notes start -->` marker.
1. Deletes the individual newsfragment files.
1. Commits both alongside the version bump in the `chore: release vX.Y.Z` commit.

The same rendered section is the GitHub Release body — `gh release create` is deliberately called without `--generate-notes`, so the release notes are exactly what the fragments say rather than a commit dump. Scheduled releases that carry no fragments leave `CHANGELOG.md` untouched rather than adding an empty section.

Unlike infrahub, `[tool.towncrier]` here sets no `package`: no importable module carries the released version, so `towncrier build` always needs an explicit `--version`. Both the workflow and `invoke release.draft` pass one.

## Relationship to the docs-site changelog

[`docs/docs/changelog.md`](../../docs/docs/changelog.md) is a separate, hand-written page: curated narrative release notes for notable features, with "What's new" and "Migration" sections. It is not generated from newsfragments and is not a substitute for one.
