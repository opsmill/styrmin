"""Documented allow-list for unauthenticated GraphQL fields. See ADR-020.

Two layers consult this list: the ``RequiresAuthentication`` schema
extension at request time, and the schema-walk completeness test in CI.
A name added here is reviewable in the same PR that adds the unguarded
field — there is no externalised config that would let an unguarded
field ship through config drift.
"""

from __future__ import annotations

#: Mutation fields that may be invoked without an authenticated session.
#:
#: ``login`` is the entry point; gating it would lock everyone out.
#:
#: ``callback``, ``report_pod_statuses``, ``report_deployment_statuses`` are
#: agent-to-server endpoints called from Prefect workflows and the in-cluster
#: status reporter. They have no caller user identity in v1; a follow-up
#: issue introduces service-account session tokens so these can move to
#: ``RequiresRole(ADMIN)``. Documented here so the gap is auditable.
#: TODO(#188): replace agent allow-list entries with service-account auth.
MUTATION_ALLOW_LIST: frozenset[str] = frozenset(
    {
        "login",
        "callback",
        "reportPodStatuses",
        "reportDeploymentStatuses",
    }
)

#: Query fields that may be invoked without an authenticated session.
#:
#: ``currentUser`` returns null when unauthenticated so that callers booting
#: the app distinguish "logged out" from "errored" without an error branch.
QUERY_ALLOW_LIST: frozenset[str] = frozenset({"currentUser", "ok"})
