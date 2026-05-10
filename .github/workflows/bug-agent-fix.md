---
description: Run the bug-fix stage of the bug-fixing pipeline.
on:
  slash_command:
    name: bug-fix
    events: [issue_comment]
engine: claude
permissions:
  contents: read
  issues: read
  pull-requests: read
  actions: read
concurrency:
  group: bug-pipeline-${{ github.event.issue.number }}
  cancel-in-progress: false
checkout:
  fetch-depth: 0
safe-outputs:
  create-pull-request:
    draft: true
    max: 1
  add-comment:
    max: 5
---

/bug-fix ${{ github.event.issue.number }}
