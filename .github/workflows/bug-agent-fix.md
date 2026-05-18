---
description: Run the bug-fix stage of the bug-fixing pipeline.
on:
  github-app:
    client-id: ${{ secrets.GH_AW_APP_ID }}
    private-key: ${{ secrets.GH_AW_APP_PRIVATE_KEY }}
  slash_command:
    name: bug-fix
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
  create-pull-request:
    draft: true
    max: 1
  add-comment:
    max: 5
---

/bug-fix ${{ github.event.issue.number }}
