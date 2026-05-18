---
description: Run the bug-review stage of the bug-fixing pipeline.
on:
  github-app:
    client-id: ${{ secrets.GH_AW_APP_ID }}
    private-key: ${{ secrets.GH_AW_APP_PRIVATE_KEY }}
  slash_command:
    name: bug-review
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
  github-app:
    client-id: ${{ secrets.GH_AW_APP_ID }}
    private-key: ${{ secrets.GH_AW_APP_PRIVATE_KEY }}
  add-comment:
    max: 5
  mark-pull-request-as-ready-for-review:
    max: 1
---

/bug-review ${{ github.event.issue.number }}
