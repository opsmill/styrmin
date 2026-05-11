---
description: Run the bug-analyze stage of the bug-fixing pipeline.
on:
  slash_command:
    name: bug-analyze
    events: [issue_comment]
  skip-bots:
    - cloudflare-pages[bot]
    - cloudflare-workers-and-pages[bot]
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
---

/bug-analyze ${{ github.event.issue.number }}
