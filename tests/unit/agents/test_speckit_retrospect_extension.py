from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def read_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text()


def test_speckit_retrospect_extension_registers_command() -> None:
    manifest = read_text(".specify/extensions/retrospect/extension.yml")
    registry = read_text(".specify/extensions/.registry")

    assert 'id: "retrospect"' in manifest
    assert 'name: "speckit.retrospect.run"' in manifest
    assert 'aliases: ["speckit.retrospect"]' in manifest
    assert 'file: "commands/retrospect.md"' in manifest
    assert '"retrospect": {' in registry
    assert '"speckit.retrospect"' in registry
    assert '"speckit.retrospect.run"' in registry
    assert (REPO_ROOT / ".agents/skills/speckit-retrospect/SKILL.md").exists()
    assert (REPO_ROOT / ".agents/skills/speckit-retrospect-run/SKILL.md").exists()


def test_speckit_retrospect_runtime_command_points_to_extension() -> None:
    command = read_text(".agents/commands/speckit.retrospect.run.md")
    command_agent = read_text(".agents/commands/speckit.retrospect.run.agent.md")
    alias = read_text(".agents/commands/speckit.retrospect.md")
    alias_agent = read_text(".agents/commands/speckit.retrospect.agent.md")
    source = read_text(".specify/extensions/retrospect/commands/retrospect.md")

    assert read_text(".claude/commands/speckit.retrospect.run.md") == command
    assert read_text(".claude/commands/speckit.retrospect.md") == alias
    assert read_text(".claude/commands/speckit.retrospect.run.agent.md") == command_agent
    assert read_text(".claude/commands/speckit.retrospect.agent.md") == alias_agent
    assert read_text(".github/prompts/speckit.retrospect.run.prompt.md") == "---\nagent: speckit.retrospect.run\n---\n"
    assert read_text(".github/prompts/speckit.retrospect.prompt.md") == "---\nagent: speckit.retrospect\n---\n"
    assert "description: Run a session retrospective" in command
    assert "description: Run a session retrospective" in alias
    assert "<!-- Extension: retrospect -->" in command
    assert "<!-- Extension: retrospect -->" in alias
    assert "<!-- Config: .specify/extensions/retrospect/ -->" in command
    assert "## Phase 1: Resolve Session Context" in source
    assert "read-only until the user approves" in command


def test_speckit_retrospect_extension_command_covers_required_workflow() -> None:
    command = read_text(".specify/extensions/retrospect/commands/retrospect.md")

    for expected in [
        "Instructions / Configuration Gaps",
        "Documentation Gaps",
        "Architectural Friction",
        "Mistakes & Corrections",
        "fix-now",
        "open-pr",
        "github-issue",
        "local-only",
        "create-issue",
        "Respect `AGENTS.md` guardrails",
        "Never edit generated files",
        "specs/<current-feature>/retrospective.md",
        ".claude/retrospectives/YYYYMMDD-HHMMSS-<short-branch-or-session-slug>.md",
    ]:
        assert expected in command
