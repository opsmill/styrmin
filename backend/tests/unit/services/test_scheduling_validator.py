"""Unit tests for the scheduling validator.

Covers T030b (component-name validation) and T034 (deployment-reference
resolution happy path + unresolvable → ``UnresolvableAffinityReferenceError``).
Further coverage (runtime-class existence, quantity syntax) lands in
later user-story phases.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from styrmin_backend.context.models.config import (
    AffinityBlock,
    AffinityTerm,
    DeploymentReference,
    LabelSelector,
    SchedulingConfig,
)
from styrmin_backend.context.resolvers import _resolve_scheduling_config
from styrmin_backend.domain.models import (
    Deployment,
    DeploymentState,
)
from styrmin_backend.services.exceptions import (
    UnknownComponentInConfigError,
    UnresolvableAffinityReferenceError,
)
from styrmin_backend.services.scheduling.validator import (
    expand_deployment_references,
    resolve_deployment_reference,
)


def _make_deployment(
    *, id: UUID | None = None, name: str, environment_id: UUID
) -> Deployment:
    return Deployment(
        id=id or uuid4(),
        name=name,
        application_version="1.0.0",
        config=None,
        application_driver_version_id=uuid4(),
        environment_id=environment_id,
        status=DeploymentState.PENDING,
    )


class TestComponentNameValidation:
    def test_unknown_component_raises_with_path(self) -> None:
        with pytest.raises(UnknownComponentInConfigError) as exc:
            _resolve_scheduling_config(
                env=None,
                dep=None,
                comp=SchedulingConfig(runtime_class="kata"),
                driver_components=["server", "cache"],
                component_name="unknown-name",
            )
        assert exc.value.error_metadata["component_name"] == "unknown-name"
        assert exc.value.error_metadata["path"] == (
            "scheduling.components.unknown-name"
        )

    def test_known_component_does_not_raise(self) -> None:
        _resolve_scheduling_config(
            env=None,
            dep=None,
            comp=SchedulingConfig(runtime_class="kata"),
            driver_components=["server"],
            component_name="server",
        )

    def test_driver_components_none_skips_check(self) -> None:
        _resolve_scheduling_config(
            env=None,
            dep=None,
            comp=SchedulingConfig(runtime_class="kata"),
            driver_components=None,
            component_name="anything",
        )


class TestInvalidSchedulingConfigError:
    """T058: the ``InvalidSchedulingConfigError`` raised by the context
    service when a scheduling payload fails Pydantic validation carries a
    ``path`` pointing at the offending level so the API layer can forward
    it via ``StructuredErrorExtension``.
    """

    def test_invalid_cpu_quantity_surfaces_path(self) -> None:
        from styrmin_backend.services.context import _extract_scheduling
        from styrmin_backend.services.exceptions import (
            InvalidSchedulingConfigError,
        )

        with pytest.raises(InvalidSchedulingConfigError) as exc:
            _extract_scheduling(
                {"scheduling": {"resources": {"requests": {"cpu": "two cores"}}}},
                path="deployment.config.scheduling",
            )
        assert exc.value.error_metadata["path"] == "deployment.config.scheduling"
        assert "cpu" in str(exc.value).lower() or "quantity" in str(exc.value).lower()


class TestResolveDeploymentReferenceById:
    """T034: happy path — DeploymentReference(deployment_id=X) expands into a
    LabelSelector keyed on ``styrmin/deployment_id``.
    """

    @pytest.mark.anyio
    async def test_resolves_by_id(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        target = _make_deployment(name="api", environment_id=env_id)
        await uow.deployments.save(target)

        selector = await resolve_deployment_reference(
            uow,
            environment_id=env_id,
            ref=DeploymentReference(deployment_id=target.id),
        )

        assert selector.match_labels == {"styrmin/deployment_id": str(target.id)}
        assert selector.match_expressions is None

    @pytest.mark.anyio
    async def test_resolves_by_name(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        target = _make_deployment(name="api", environment_id=env_id)
        await uow.deployments.save(target)

        selector = await resolve_deployment_reference(
            uow,
            environment_id=env_id,
            ref=DeploymentReference(deployment_name="api"),
        )

        assert selector.match_labels == {"styrmin/deployment_id": str(target.id)}

    @pytest.mark.anyio
    async def test_narrows_by_components(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        target = _make_deployment(name="api", environment_id=env_id)
        await uow.deployments.save(target)

        selector = await resolve_deployment_reference(
            uow,
            environment_id=env_id,
            ref=DeploymentReference(
                deployment_id=target.id, components=["server", "worker"]
            ),
        )

        assert selector.match_labels == {"styrmin/deployment_id": str(target.id)}
        assert selector.match_expressions is not None
        assert len(selector.match_expressions) == 1
        req = selector.match_expressions[0]
        assert req.key == "styrmin/component"
        assert req.operator == "In"
        assert req.values == ["server", "worker"]


class TestResolveDeploymentReferenceUnresolvable:
    """T034: unresolvable — target not found, OR found but in a different
    environment, raises ``UnresolvableAffinityReferenceError`` with a
    ``path`` that identifies the offending term.
    """

    @pytest.mark.anyio
    async def test_missing_id_raises(self, uow) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await resolve_deployment_reference(
                uow,
                environment_id=uuid4(),
                ref=DeploymentReference(deployment_id=uuid4()),
                path="scheduling.pod_affinity.required[0]",
            )
        assert exc.value.error_metadata["path"] == (
            "scheduling.pod_affinity.required[0]"
        )

    @pytest.mark.anyio
    async def test_missing_name_raises(self, uow) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await resolve_deployment_reference(
                uow,
                environment_id=uuid4(),
                ref=DeploymentReference(deployment_name="nope"),
            )
        assert exc.value.error_metadata["deployment_name"] == "nope"

    @pytest.mark.anyio
    async def test_different_environment_raises(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_a = uuid4()
        env_b = uuid4()
        target = _make_deployment(name="api", environment_id=env_a)
        await uow.deployments.save(target)

        with pytest.raises(UnresolvableAffinityReferenceError):
            await resolve_deployment_reference(
                uow,
                environment_id=env_b,
                ref=DeploymentReference(deployment_id=target.id),
            )


class TestExpandDeploymentReferences:
    """End-to-end expansion: a resolved SchedulingConfig with a deployment_ref
    term is rewritten to carry an equivalent label_selector, preserving other
    fields untouched.
    """

    @pytest.mark.anyio
    async def test_expands_pod_affinity_ref_to_label_selector(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        target = _make_deployment(name="api", environment_id=env_id)
        await uow.deployments.save(target)

        config = SchedulingConfig(
            pod_affinity=AffinityBlock(
                required=[
                    AffinityTerm(
                        topology_key="kubernetes.io/hostname",
                        deployment_ref=DeploymentReference(deployment_id=target.id),
                    )
                ]
            )
        )

        expanded = await expand_deployment_references(uow, env_id, config)

        assert expanded.pod_affinity is not None
        term = expanded.pod_affinity.required[0]
        assert term.deployment_ref is None
        assert term.label_selector is not None
        assert term.label_selector.match_labels == {
            "styrmin/deployment_id": str(target.id)
        }

    @pytest.mark.anyio
    async def test_preserves_existing_label_selectors(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        config = SchedulingConfig(
            pod_affinity=AffinityBlock(
                required=[
                    AffinityTerm(
                        topology_key="kubernetes.io/hostname",
                        label_selector=LabelSelector(match_labels={"app": "web"}),
                    )
                ]
            )
        )

        expanded = await expand_deployment_references(uow, env_id, config)

        assert expanded.pod_affinity is not None
        term = expanded.pod_affinity.required[0]
        assert term.label_selector is not None
        assert term.label_selector.match_labels == {"app": "web"}


class TestRuntimeClassValidation:
    """Runtime-class syntactic validation. Cluster-side existence checks
    were removed when the allow-list was dropped — any DNS-1123 name is
    accepted and surfaces later as a Pending pod if the cluster does not
    install the referenced RuntimeClass."""

    def test_dns_1123_syntactic_validation(self) -> None:
        """``runtime_class`` must be a DNS-1123 subdomain."""
        from pydantic import ValidationError
        from styrmin_backend.context.models.config import SchedulingConfig

        SchedulingConfig(runtime_class="kata")
        SchedulingConfig(runtime_class="kata-fc")
        SchedulingConfig(runtime_class="runtime.example.com")
        with pytest.raises(ValidationError):
            SchedulingConfig(runtime_class="UPPER")
        with pytest.raises(ValidationError):
            SchedulingConfig(runtime_class="-leading-dash")
        with pytest.raises(ValidationError):
            SchedulingConfig(runtime_class="")
