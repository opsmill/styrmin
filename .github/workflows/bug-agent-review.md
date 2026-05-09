---
description: Run the bug-review stage of the bug-fixing pipeline.
on:
  slash_command:
    name: bug-review
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
  add-comment:
    max: 5
  update-pull-request:
    max: 1
  mark-pull-request-as-ready-for-review:
    max: 1
---

/bug-review ${{ github.event.issue.number }}
