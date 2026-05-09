---
description: Run the bug-test stage of the bug-fixing pipeline.
on:
  slash_command:
    name: bug-test
    events: [issue_comment]
engine: claude
permissions:
  contents: write
  pull-requests: write
  issues: write
  id-token: write
  actions: read
concurrency:
  group: bug-pipeline-${{ github.event.issue.number }}
  cancel-in-progress: false
checkout:
  fetch-depth: 0
anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
---

/bug-test ${{ github.event.issue.number }}
