# Follow-ups

## Automated dual-stack IPv6 *traffic* E2E coverage

**Source**: `specs/001-ingress-ipfamily-nodeport/` (this iteration), `plan.md`
Complexity Tracking, `tasks.md` T023.

This iteration ships:

- Unit + snapshot coverage for the new `ip_families` / `ip_family_policy`
  / `node_port` knobs on `IngressServiceConfig`.
- An automated E2E (`test_dedicated_ingress_service_overrides`) that
  proves the *rendering* layer reaches the cluster — it deploys with all
  three knobs set on the existing single-family vcluster and asserts on
  the resulting Service object.
- A manual-validation runbook for cluster-side IPv6 traffic
  (`dev/guides/ingress-ipv6-dual-stack-validation.md`).

The remaining §V gap is narrow: cluster-side IPv6 *traffic* validation
(AAAA publication, v6 routing) requires dual-stack infrastructure that
CI does not currently provide.

### What this follow-up should do

1. Introduce a dual-stack vcluster fixture (or equivalent — kind /
   external cluster wiring is acceptable if vcluster cannot deliver
   dual-stack on the build hosts).
2. Add an E2E that deploys with `ip_families: ["IPv6"]` +
   `ip_family_policy: "SingleStack"` and asserts cluster-side traffic
   actually flows on v6 — at minimum AAAA resolution against the
   ingress FQDN and a v6-capable client request returning `200`.
3. Replace the manual runbook step in
   `dev/guides/ingress-ipv6-dual-stack-validation.md` with a pointer to
   the automated assertion (keep the runbook as historical context for
   operators who still hit the legacy single-family infra).

The §V "narrowed deviation" recorded in `plan.md` Complexity Tracking
is closed only when the automated assertion lands.

### Suggested triggering action

Open a GitHub issue (or a new `specs/<NNN>-dual-stack-e2e/` spec) that
references this directory and tracks the work above. The current task
list intentionally does not file the issue automatically — it requires a
GitHub-side action (publishing visible work) that should be authored by
a human.
