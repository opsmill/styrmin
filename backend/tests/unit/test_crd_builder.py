"""Unit tests for :func:`build_styrmin_deployment_body`.

Every deployment on the platform goes through this builder, and its most
load-bearing decision is invisible for all but one of them: the CR is named
after its **namespace**, not after the Helm release reference. The two strings
are the same for an ordinary deployment (``get_kubernetes_reference`` derives
both from the deployment id), so a regression to ``"name": release_reference``
changes nothing observable — until an environment clone's counterpart, which
keeps its own namespace while *adopting the source's* release name (010
research D2). Then the CR would be named after the source, the status reporter,
``delete_deployment`` and the operator janitor would all look for a CR that is
not there, and only a 20-minute E2E would notice.

So the split is pinned here directly, on a counterpart-shaped input where the
two strings genuinely differ, plus the ordinary case as the negative control.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.operator.config import (
    ANNOTATION_INSTANCE_SEQUENCE,
    CRD_GROUP,
    CRD_KIND,
    CRD_VERSION,
    LABEL_MANAGED_BY,
    LABEL_MANAGED_BY_VALUE,
)
from styrmin_backend.operator.crd.builder import build_styrmin_deployment_body

from tests.unit.counterpart_crd_fixtures import (
    COUNTERPART_DEPLOYMENT_ID,
    COUNTERPART_NAMESPACE,
    SOURCE_DEPLOYMENT_ID,
    SOURCE_RELEASE_REFERENCE,
    counterpart_context,
    make_context,
)


def test_the_cr_is_named_after_the_namespace_not_the_release_reference() -> None:
    """The one case where the two strings differ — a clone counterpart.

    ``metadata.name`` must follow the namespace; the *release* name goes to
    ``spec.releaseReference`` only. Reverting the builder to
    ``"name": release_reference`` would name this CR after the source
    deployment, in the counterpart's namespace.
    """
    instance_id = uuid4()
    body = build_styrmin_deployment_body(
        context=counterpart_context(instance_id),
        release_reference=SOURCE_RELEASE_REFERENCE,
        namespace=COUNTERPART_NAMESPACE,
    )

    assert SOURCE_RELEASE_REFERENCE != COUNTERPART_NAMESPACE, (
        "the fixture must actually exercise the divergence, otherwise this "
        "test cannot fail"
    )
    assert body["metadata"]["name"] == COUNTERPART_NAMESPACE
    assert body["metadata"]["namespace"] == COUNTERPART_NAMESPACE
    # ...while the adopted Helm release name reaches the spec, and only there.
    assert body["spec"]["releaseReference"] == SOURCE_RELEASE_REFERENCE
    # Identity is the counterpart's throughout — this CR is not a copy of the
    # source's CR with a different name.
    assert body["spec"]["deploymentId"] == str(COUNTERPART_DEPLOYMENT_ID)
    assert body["spec"]["instanceId"] == str(instance_id)


def test_an_ordinary_deployment_collapses_the_two_names() -> None:
    """The negative control: every non-counterpart deployment.

    Namespace and release reference are both ``styrmin-<deployment id>`` here,
    so the CR name is that string either way. Pinned so the change that made
    the counterpart case work is proven not to have moved anything for the
    99% path.
    """
    namespace = f"styrmin-{SOURCE_DEPLOYMENT_ID}"
    body = build_styrmin_deployment_body(
        context=make_context(
            deployment_id=SOURCE_DEPLOYMENT_ID,
            namespace=namespace,
            release_reference=namespace,
        ),
        release_reference=namespace,
        namespace=namespace,
    )

    assert body["metadata"]["name"] == namespace
    assert body["metadata"]["namespace"] == namespace
    assert body["spec"]["releaseReference"] == namespace


def test_the_envelope_and_managed_by_label_are_the_operator_contract() -> None:
    """apiVersion / kind / managed-by are what makes the operator watch this CR."""
    body = build_styrmin_deployment_body(
        context=counterpart_context(),
        release_reference=SOURCE_RELEASE_REFERENCE,
        namespace=COUNTERPART_NAMESPACE,
    )

    assert body["apiVersion"] == f"{CRD_GROUP}/{CRD_VERSION}"
    assert body["kind"] == CRD_KIND
    assert body["metadata"]["labels"] == {LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE}


def test_the_spec_carries_the_whole_resolved_context_and_helm_binding() -> None:
    """The operator renders the chart from the spec alone, so it must be complete."""
    context = counterpart_context()
    body = build_styrmin_deployment_body(
        context=context,
        release_reference=SOURCE_RELEASE_REFERENCE,
        namespace=COUNTERPART_NAMESPACE,
        internal=True,
    )

    spec = body["spec"]
    assert spec["appName"] == "simple-app"
    assert spec["appVersion"] == "1.6.0"
    assert spec["internal"] is True
    assert spec["labels"] == {"deployment_id": str(COUNTERPART_DEPLOYMENT_ID)}
    assert spec["parameters"] == {"license": "ent"}
    assert spec["helm"] == {
        "chart": {
            "id": str(context.app.helm.chart.id),
            "name": "simple-app",
            "version": "0.1.0",
            "values_template": "name: {{ app.name }}",
        },
        "repository": {
            "id": str(context.app.helm.repository.id),
            "url": "https://helm.example.com",
        },
    }
    # The embedded context is the same one, JSON-round-trippable: the operator
    # revalidates it, so a non-serialisable value here breaks reconciliation.
    assert spec["context"]["instance"]["release_reference"] == SOURCE_RELEASE_REFERENCE
    assert spec["context"]["instance"]["namespace"] == COUNTERPART_NAMESPACE
    assert GlobalContext.model_validate(spec["context"]) == context


def test_a_context_without_an_instance_id_reports_none_rather_than_a_string() -> None:
    """``instanceId`` is nullable in the CRD schema; ``"None"`` is not null."""
    body = build_styrmin_deployment_body(
        context=counterpart_context(instance_id=None),
        release_reference=SOURCE_RELEASE_REFERENCE,
        namespace=COUNTERPART_NAMESPACE,
    )

    assert body["spec"]["instanceId"] is None


@pytest.mark.parametrize("internal", [True, False])
def test_internal_defaults_to_false_and_is_passed_through(internal: bool) -> None:
    body = build_styrmin_deployment_body(
        context=counterpart_context(),
        release_reference=SOURCE_RELEASE_REFERENCE,
        namespace=COUNTERPART_NAMESPACE,
        internal=internal,
    )
    assert body["spec"]["internal"] is internal

    default = build_styrmin_deployment_body(
        context=counterpart_context(),
        release_reference=SOURCE_RELEASE_REFERENCE,
        namespace=COUNTERPART_NAMESPACE,
    )
    assert default["spec"]["internal"] is False


def test_the_instance_sequence_is_recorded_in_an_annotation() -> None:
    """The agent compares it with the live StyrminDeployment's to keep a newer instance (#386)."""
    context = counterpart_context(uuid4())

    body = build_styrmin_deployment_body(
        context=context,
        release_reference=SOURCE_RELEASE_REFERENCE,
        namespace=COUNTERPART_NAMESPACE,
        instance_sequence=7,
    )
    without = build_styrmin_deployment_body(
        context=context,
        release_reference=SOURCE_RELEASE_REFERENCE,
        namespace=COUNTERPART_NAMESPACE,
    )

    assert body["metadata"]["annotations"] == {ANNOTATION_INSTANCE_SEQUENCE: "7"}
    assert "annotations" not in without["metadata"]
