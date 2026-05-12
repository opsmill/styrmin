---
description: Run the bug-test stage of the bug-fixing pipeline.
on:
  slash_command:
    name: bug-test
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
  group: bug-pipeline-${{ github.workflow }}-${{ github.event.issue.number }}
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
