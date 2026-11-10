"""``apply_utility_resources`` applies the utility resources and reports the failures that matter (#598, review F2).

An Ingress and a NetworkPolicy belong to ``networking.k8s.io/v1``, so the flow puts them with the
custom resources, whose kind may not be installed yet. Only a refusal with status 404 (the kind is not
installed) may be skipped. The error of an Ingress must fail the flow, as the Ingress is the only
object that makes a service reachable.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from kubernetes_asyncio.client.api_client import ApiException
from loguru import logger

from styrmin_backend.agent.tasks import application as application_module

NAMESPACE = "styrmin-abc"


def _resource(api_version: str, kind: str, name: str) -> dict[str, Any]:
    return {
        "apiVersion": api_version,
        "kind": kind,
        "metadata": {"name": name, "namespace": NAMESPACE},
    }


INGRESS = _resource("networking.k8s.io/v1", "Ingress", "styrmin-svc-web")
NETWORK_POLICY = _resource("networking.k8s.io/v1", "NetworkPolicy", "allow-web")
MIDDLEWARE = _resource("traefik.io/v1alpha1", "Middleware", "acl")
SECRET = _resource("v1", "Secret", "tls")


@pytest.fixture
def log_lines() -> Any:
    lines: list[str] = []
    sink_id = logger.add(lambda message: lines.append(str(message)), level="WARNING")
    yield lines
    logger.remove(sink_id)


def _patch_apply(mocker: Any, errors: dict[str, ApiException]) -> AsyncMock:
    """Patch the two calls of the flow; a resource whose kind is in ``errors`` is refused."""
    mocker.patch.object(application_module, "apply_namespace", AsyncMock())

    async def _apply(*, resource: dict[str, Any], namespace: str) -> None:
        error = errors.get(resource["kind"])
        if error is not None:
            raise error

    apply = AsyncMock(side_effect=_apply)
    mocker.patch.object(application_module, "apply_kubernetes_resource", apply)
    return apply


@pytest.mark.anyio
@pytest.mark.parametrize("status", [403, 422, 500])
async def test_a_refused_ingress_fails_the_flow(mocker: Any, status: int) -> None:
    _patch_apply(mocker, {"Ingress": ApiException(status=status, reason="refused")})

    with pytest.raises(ApiException) as error:
        await application_module.apply_utility_resources.fn(
            namespace=NAMESPACE, resources=[SECRET, INGRESS]
        )

    assert error.value.status == status


@pytest.mark.anyio
async def test_a_custom_kind_that_is_not_installed_is_skipped_and_logged_with_its_status(
    mocker: Any, log_lines: list[str]
) -> None:
    apply = _patch_apply(
        mocker, {"Middleware": ApiException(status=404, reason="Not Found")}
    )

    await application_module.apply_utility_resources.fn(
        namespace=NAMESPACE, resources=[MIDDLEWARE, INGRESS]
    )

    assert apply.await_count == 2
    (line,) = log_lines
    assert "Middleware/acl" in line
    assert "404" in line
    assert "Not Found" in line


@pytest.mark.anyio
async def test_a_custom_kind_refused_for_another_reason_fails_the_flow(
    mocker: Any,
) -> None:
    _patch_apply(mocker, {"Middleware": ApiException(status=422, reason="Invalid")})

    with pytest.raises(ApiException) as error:
        await application_module.apply_utility_resources.fn(
            namespace=NAMESPACE, resources=[MIDDLEWARE]
        )

    assert error.value.status == 422


@pytest.mark.anyio
async def test_a_refused_network_policy_is_still_skipped_but_logged_with_status_and_reason(
    mocker: Any, log_lines: list[str]
) -> None:
    """Behaviour kept as it was (left open in the review): only the log text gains the status and reason."""
    _patch_apply(
        mocker, {"NetworkPolicy": ApiException(status=403, reason="Forbidden")}
    )

    await application_module.apply_utility_resources.fn(
        namespace=NAMESPACE, resources=[NETWORK_POLICY]
    )

    (line,) = log_lines
    assert "NetworkPolicy/allow-web" in line
    assert "403" in line
    assert "Forbidden" in line
