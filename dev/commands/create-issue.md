# Create GitHub Issue

## Introduction

Transform feature descriptions, bug reports, or improvement ideas into well-structured GitHub issues that follow project conventions and best practices. This command provides flexible detail levels to match your needs.

## Prerequisites

- GitHub CLI (`gh`) installed and authenticated
- Access to the target repository
- Understanding of the feature/bug/improvement to document

## Feature Description

<feature_description> #$ARGUMENTS </feature_description>

## Main Tasks

### 1. Repository Research & Context Gathering

<thinking>
First, I need to understand the project's conventions and existing patterns, leveraging all available resources
</thinking>

**Internal Repository Research:**

- [ ] Examine repository structure and architecture files in `dev/`
- [ ] Analyze existing GitHub issues for formatting patterns and label usage
- [ ] Review project documentation for issue submission guidelines
- [ ] Check for issue templates in `.github/ISSUE_TEMPLATE/`

**External Best Practices Research:**

- [ ] Search web for issue creation best practices specific to the technology stack
- [ ] Find examples of well-written issues in similar open source projects
- [ ] Research domain-specific terminology and conventions

**Reference Collection:**

- [ ] Include URLs to external documentation and best practices guides
- [ ] Create a reference list of similar issues or PRs (e.g., `#123`, `#456`)
- [ ] Note any team conventions discovered in `CLAUDE.md` or team documentation

### 2. Issue Planning & Structure

<thinking>
Think like a product manager - what would make this issue clear and actionable? Consider multiple perspectives
</thinking>

**Title & Categorization:**

- [ ] Draft clear, searchable issue title using conventional format (e.g., `feat:`, `fix:`, `docs:`)
- [ ] Identify appropriate labels from repository's label set (`gh label list`)
- [ ] Determine issue type: enhancement, bug, documentation, refactor
- [ ] Consider adding priority labels if available (P0, P1, P2 or critical, high, medium, low)

**Stakeholder Analysis:**

- [ ] Identify who will be affected by this issue (end users, developers, operations)
- [ ] Note any cross-team dependencies or coordination needs

**Content Planning:**

- [ ] Choose appropriate detail level based on issue complexity and audience
- [ ] List all necessary sections for the chosen template
- [ ] Gather supporting materials (error logs, screenshots, design mockups)

### 3. Choose Implementation Detail Level

Select how comprehensive you want the issue to be:

#### 📄 MINIMAL (Quick Issue)

**Best for:** Simple bugs, small improvements, clear features

**Includes:**

- Problem statement or feature description
- Basic acceptance criteria
- Essential context only

**Structure:**

```markdown
## Description

[Brief problem/feature description]

## Acceptance Criteria

- [ ] Core requirement 1
- [ ] Core requirement 2

## Context

[Any critical information]

## References

- Related issue: #[issue_number]
- Documentation: [relevant_docs_url]
```

#### 📋 MORE (Standard Issue)

**Best for:** Most features, complex bugs, team collaboration

**Includes everything from MINIMAL plus:**

- Detailed background and motivation
- Success metrics

**Structure:**

```markdown
## Overview

[Comprehensive description]

## Problem Statement / Motivation

[Why this matters — user pain, business need, or technical debt]

## Acceptance Criteria

- [ ] Detailed requirement 1
- [ ] Detailed requirement 2
- [ ] Testing requirements

## Success Metrics

[How we measure success]
```

#### 📚 A LOT (Comprehensive Issue)

**Best for:** Major features, architectural changes, complex integrations

**Includes everything from MORE plus:**

- Detailed problem analysis with user/business impact
- Comprehensive acceptance criteria (functional, non-functional, quality gates)

**Structure:**

```markdown
## Overview

[Executive summary]

## Problem Statement

[Detailed problem analysis — who is affected, how, and what is the impact]

## Acceptance Criteria

### Functional Requirements

- [ ] Detailed functional criteria

### Non-Functional Requirements

- [ ] Performance targets
- [ ] Security requirements
- [ ] Accessibility standards

### Quality Gates

- [ ] Test coverage requirements
- [ ] Documentation completeness
- [ ] Code review approval

## Success Metrics

[Detailed KPIs and measurement methods]

## Related Issues

- #[issue_numbers]
```

### 4. Issue Creation & Formatting

<thinking>
Apply best practices for clarity and actionability, making the issue easy to scan and understand
</thinking>

**Content Formatting:**

- [ ] Use clear, descriptive headings with proper hierarchy (##, ###)
- [ ] Add screenshots/mockups if UI-related (drag & drop or use image hosting)
- [ ] Use task lists (- [ ]) for trackable items that can be checked off
- [ ] Add collapsible sections for lengthy logs or optional details using `<details>` tags
- [ ] Apply appropriate emoji for visual scanning (🐛 bug, ✨ feature, 📚 docs, ♻️ refactor)

**Cross-Referencing:**

- [ ] Link to related issues/PRs using #number format
- [ ] Reference specific commits with SHA hashes when relevant
- [ ] Link to code using GitHub's permalink feature (press 'y' for permanent link)
- [ ] Mention relevant team members with @username if needed
- [ ] Add links to external resources with descriptive text

**AI-Era Considerations:**

- [ ] Write clear problem descriptions that can serve as effective prompts for implementation agents
- [ ] Include enough context for an AI agent to understand the problem without prior knowledge
- [ ] Emphasize comprehensive acceptance criteria to guide automated implementation

### 5. User Validation & Submission

**IMPORTANT: Always present the draft issue to the user for review and approval BEFORE creating it.** Even if you have CLI permissions to run `gh issue create` directly, you MUST ask the user to validate the issue content first. Never create an issue without explicit user approval.

**Pre-submission Checklist:**

- [ ] Title is searchable and descriptive
- [ ] Labels accurately categorize the issue
- [ ] All template sections are complete
- [ ] Acceptance criteria are measurable
- [ ] **User has reviewed and approved the issue content**

## Output Format

1. Present the complete draft issue content to the user for review
2. Wait for the user's explicit approval or requested changes
3. Only after approval, create the issue using GitHub CLI:

```bash
gh issue create --title "[TITLE]" --body "[CONTENT]" --label "[LABELS]"
```

## Thinking Approaches

- **Analytical:** Break down complex features into manageable components
- **User-Centric:** Consider end-user impact and experience
- **Strategic:** Align with project goals and roadmap

## Notes

**Issue Quality Guidelines:**

- Prioritize clarity over completeness - a clear MINIMAL issue beats a confusing comprehensive one
- Consider your audience: maintainers need different details than contributors
- Write for future you - include context you'll forget in 6 months
- Make issues self-contained - minimize need to reference external discussions

**Modern Development Considerations:**

- Write problem descriptions that are clear enough to serve as effective prompts for implementation agents
- Focus on observable outcomes and acceptance criteria rather than implementation prescriptions

## Expected Outcome

A well-structured GitHub issue that:

- Clearly communicates the problem and desired outcome
- Provides appropriate detail for the chosen level
- Follows project conventions
- Focuses on **what** and **why**, leaving implementation to a separate agent
- Facilitates team collaboration
