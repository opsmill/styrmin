# Markdown Guidelines

## Tooling

- **Linter:** rumdl
- **Excluded directories:** `.venv`, `node_modules`, `dev`, `.claude`, `specs`, `.github/agents`
- Disabled rules: MD013 (line length), MD033 (inline HTML), MD041 (first line heading), MD057 (relative links), MD060 (code block language)

## File Naming

- Use `kebab-case` for filenames: `hooks-and-actions.md`, `data-models.md`
- Use descriptive names that reflect the document's primary topic

## Document Structure

Every document should start with a top-level heading (`#`) matching its topic:

```markdown
# Topic Name

## Overview

Brief description of what this document covers.

## Sections...
```

## Documentation Categories

Documents follow a lifecycle and belong to one category:

| Category | Path | Purpose | Style |
|----------|------|---------|-------|
| Knowledge | `dev/knowledge/` | How the system works | Descriptive reference |
| Guidelines | `dev/guidelines/` | How code should be written | Prescriptive rules |
| Guides | `dev/guides/` | Step-by-step procedures | Task-oriented |
| ADRs | `dev/adr/` | Why decisions were made | Decision records |
| Specs | `specs/` | What is being built | Design documents |
| Explorations | `dev/explorations/` | Rough ideas and spikes | Informal |

Lifecycle: `explorations/ -> specs/ -> knowledge/ or guidelines/`

## Code Blocks

Use fenced code blocks with language identifiers:

````markdown
```python
def example():
    pass
```

```text
Diagram or plain text here
```
````

## Tables

Use pipe tables for structured data:

```markdown
| Column 1 | Column 2 |
|----------|----------|
| Value    | Value    |
```

## Key Files Tables

Knowledge documents should end with a "Key Files" table linking to relevant source files:

```markdown
## Key Files

| File | Purpose |
|------|---------|
| [path/to/file.py](path/to/file.py) | Brief description |
```

## Deprecation

Mark deprecated docs clearly. Don't delete -- update with pointers to replacements.
