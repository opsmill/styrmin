---
description: Run the bug-test stage of the bug-fixing pipeline.
on:
  slash_command:
    name: bug-test
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
  push-to-pull-request-branch:
    max: 1
  add-comment:
    max: 5
---

/bug-test ${{ github.event.issue.number }}
