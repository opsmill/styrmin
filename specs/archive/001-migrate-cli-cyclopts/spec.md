# Feature Specification: Migrate styrminctl CLI from Typer to Cyclopts

**Feature Branch**: `001-migrate-cli-cyclopts`
**Created**: 2026-03-25
**Status**: Extracted
**Input**: GitHub Issue [opsmill/styrmin#8](https://github.com/opsmill/styrmin/issues/8) — Migrate styrminctl CLI from Typer to Cyclopts

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run Existing CLI Commands with Faster Startup (Priority: P1)

As a platform operator or automation agent, I want to run `styrminctl` commands and receive output noticeably faster than today, so that repeated invocations (e.g., in scripted workflows or agent-driven loops) don't create frustrating delays.

**Why this priority**: Startup performance is the primary user-facing pain point. Every CLI invocation pays the cost of Typer's heavy import chain, and this compounds when the CLI is called repeatedly by automation or AI agents.

**Independent Test**: Can be fully tested by timing `styrminctl --help` and any existing command before and after migration, confirming that all existing commands still produce identical output and behavior.

**Acceptance Scenarios**:

1. **Given** a user has the migrated `styrminctl` installed, **When** they run any previously supported command (e.g., `styrminctl --help`, `styrminctl <subcommand>`), **Then** the command produces the same output and exit code as the Typer-based version.
2. **Given** an automation script calls `styrminctl` 50 times in sequence, **When** the script completes, **Then** total wall-clock time is measurably reduced compared to the Typer-based version.
3. **Given** a user runs a command with invalid arguments, **When** the CLI processes the input, **Then** the error message is clear and the exit code is non-zero, consistent with previous behavior.

---

### User Story 2 - Use Async Commands Natively (Priority: P2)

As a CLI developer, I want async commands to work natively without a custom wrapper, so that I can write async CLI handlers directly and reduce maintenance burden.

**Why this priority**: The current `AsyncTyper` wrapper is a maintenance liability. Eliminating it simplifies the codebase and removes a class of potential bugs, but this is primarily a developer-experience improvement rather than a direct user-facing change.

**Independent Test**: Can be tested by verifying that any existing async CLI command executes correctly without the `AsyncTyper` wrapper, and that new async commands can be added without special handling.

**Acceptance Scenarios**:

1. **Given** the CLI codebase has been migrated, **When** a developer inspects the code, **Then** there is no `AsyncTyper` wrapper or equivalent workaround.
2. **Given** an async CLI command exists, **When** a user invokes it, **Then** it executes correctly with proper async handling (e.g., concurrent network calls complete as expected).

---

### User Story 3 - Consistent CLI Experience Across Project Tools (Priority: P3)

As a platform operator, I want `styrminctl` and `styrmin` (backend CLI) to have consistent command patterns, help formatting, and argument conventions, so that switching between the two CLIs feels seamless.

**Why this priority**: Unifying on a single CLI framework across the project reduces cognitive overhead for operators who use both CLIs and simplifies onboarding for new team members. This is a quality-of-life improvement that follows naturally from the migration.

**Independent Test**: Can be tested by comparing help output and argument conventions between `styrminctl` and `styrmin` for analogous operations, confirming consistent style.

**Acceptance Scenarios**:

1. **Given** both `styrmin` and `styrminctl` are installed, **When** a user runs `--help` on both, **Then** the help output follows the same formatting conventions (flag style, description layout, grouping).
2. **Given** a user is familiar with `styrmin` command patterns, **When** they use `styrminctl`, **Then** analogous commands follow the same argument and flag conventions.

---

### Edge Cases

- Boolean flag negation (`--no-<flag>`) will not be preserved; Cyclopts defaults apply. This is a documented breaking change. Multi-value argument handling should follow Cyclopts conventions.
- How does the CLI behave when invoked with no arguments — does it show help or an error, consistent with previous behavior?
- Shell completions are new with this migration (none existed before). Completions will be provided via Cyclopts built-in support for bash, zsh, and fish.
- How does the CLI handle keyboard interrupts (Ctrl+C) during long-running async operations?

## Clarifications

### Session 2026-03-25

- Q: Should tests be written before, after, or alongside the migration (no existing styrminctl tests exist)? → A: Write tests alongside migration — test each command group as it's migrated.
- Q: What level of help text compatibility is required (Typer and Cyclopts format help differently)? → A: Follow Cyclopts defaults — align with backend `styrmin` CLI help style for consistency.
- Q: How should boolean flag negation be handled (Typer auto-generates `--flag/--no-flag`, Cyclopts does not by default)? → A: Use Cyclopts defaults — drop `--no-` prefix support; document the change.
- Q: Should shell completion support be in scope (no completions currently exist for styrminctl)? → A: Yes — add Cyclopts shell completion support as part of this migration.
- Q: How should `typer.Exit()` calls be migrated for exit code handling (~35 commands)? → A: Use Cyclopts' native exit handling.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The CLI MUST support all existing commands, subcommands, and flags with identical names and semantics as the current Typer-based implementation. Exception: Typer's automatic `--no-<flag>` boolean negation is dropped in favor of Cyclopts defaults; this breaking change must be documented.
- **FR-002**: The CLI MUST produce identical output (stdout/stderr) and exit codes for all existing commands under normal operation.
- **FR-003**: The CLI MUST support async command handlers natively without requiring a custom wrapper class.
- **FR-004**: The CLI MUST display help text (via `--help`) for all commands and subcommands, using Cyclopts default formatting consistent with the backend `styrmin` CLI style. Same commands, flags, and descriptions must be present; exact layout match with Typer is not required.
- **FR-005**: The CLI MUST handle invalid arguments gracefully, displaying clear error messages and returning non-zero exit codes. Exit code handling MUST use Cyclopts' native exit mechanism, replacing all `typer.Exit()` calls.
- **FR-006**: The CLI MUST remove the `AsyncTyper` wrapper and Typer dependency from the project.
- **FR-007**: The CLI MUST preserve existing environment variable and configuration file handling (if any).
- **FR-008**: The CLI MUST add shell completion support for common shells (bash, zsh, fish) using Cyclopts built-in completion capabilities. This is new functionality — no completions existed previously.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: CLI startup time (time to display `--help`) is reduced by at least 50% compared to the current Typer-based version.
- **SC-002**: 100% of CLI commands have tests written alongside the migration (per command group), and all pass. Tests are written incrementally as each command group is migrated.
- **SC-003**: The project maintains only one CLI framework dependency for command-line interfaces, eliminating Typer and the `AsyncTyper` wrapper.
- **SC-004**: All existing automation scripts and agent workflows that invoke `styrminctl` continue to work without modification.

## Assumptions

- The existing backend CLI (`styrmin`) already uses Cyclopts, providing established patterns and conventions to follow for the migration.
- The command surface area of `styrminctl` is well-defined. No CLI tests currently exist; tests will be written alongside the migration for each command group.
- Shell completion support in Cyclopts is sufficient to replace Typer's completion capabilities, or differences are minor and documentable.
- No external tools or integrations depend on Typer-specific CLI output formatting (e.g., Rich-formatted tables in terminal output) — if they do, equivalent output will be preserved.
