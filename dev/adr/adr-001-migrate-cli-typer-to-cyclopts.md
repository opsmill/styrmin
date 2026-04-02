# ADR-001: Migrate styrminctl CLI from Typer to Cyclopts

**Status**: Accepted
**Date**: 2026-04-01
**Source**: specs/archive/001-migrate-cli-cyclopts/research.md (R1, R2, R3, R9)

## Context

The `styrminctl` CLI (35 commands, 7 command groups) was built on Typer, while the backend `styrmin` CLI already used Cyclopts. This created two problems: (1) Typer's heavy import chain caused slow startup times, particularly painful for automation and AI agent workflows that invoke the CLI repeatedly; (2) Typer lacks native async support, requiring a custom `AsyncTyper` wrapper class to handle the CLI's async command handlers. Maintaining two CLI frameworks and a custom compatibility layer added unnecessary complexity.

## Decision

Migrate `styrminctl` from Typer to Cyclopts, adopting the same framework used by the backend CLI. This includes:

- Replacing `typer.App` / `typer.Option` / `typer.Argument` with `cyclopts.App` / `cyclopts.Parameter` patterns
- Eliminating the `AsyncTyper` wrapper — Cyclopts natively supports `async def` command handlers
- Replacing `raise typer.Exit(code=1)` with `raise SystemExit(1)` — the Python-standard, framework-agnostic exit mechanism
- Swapping the `typer>=0.16.0,<0.22.0` dependency for `cyclopts>=3.0.0`
- Using lazy command registration (`app.command("module:app", name="...")`) to keep startup fast

## Consequences

**Easier:**
- Single CLI framework across the entire project — lower cognitive overhead for contributors
- Async commands work natively without a wrapper class
- CLI startup is significantly faster (Cyclopts has a lighter import footprint)
- Shell completions available via Cyclopts built-in support (bash, zsh, fish) — previously absent

**Harder:**
- Boolean flag negation (`--no-<flag>`) is no longer auto-generated — users must adapt (e.g., `--wait false` instead of `--no-wait`)
- Help text layout differs from Typer's Rich-formatted output — visual change for existing users
- Import errors in lazily-loaded command modules surface at execution time rather than startup

## Alternatives Considered

- **Keep Typer with performance tuning**: Rejected — does not address the dual-framework problem or the AsyncTyper maintenance burden. Typer's import chain is inherently heavier.
- **Keep Typer, remove AsyncTyper with manual `asyncio.run()`**: Rejected — still maintains two frameworks; `asyncio.run()` wrappers add boilerplate to all 35 commands.
- **Custom CLI framework**: Rejected — unnecessary when Cyclopts is already proven in the backend CLI and meets all requirements.
