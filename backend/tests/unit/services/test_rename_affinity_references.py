"""A rename keeps the affinity rules that name the deployment pointed at it (#492).

An affinity rule may name its target deployment by ``deployment_name``, looked
up in the environment on every reconcile. Renaming the target rewrites the
name in the rules of the environment and of its deployments, so the next
reconcile of a deployment with such a rule still finds the target.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from styrmin_backend.domain.models import (
    Component,
    Deployment,
    DeploymentState,
    Task,
)
from styrmin_backend.services.deployment import (
    update_deployment,
    update_deployment_version,
)
from styrmin_backend.services.reconciliation import generate_instance_from_deployment
from styrmin_backend.services.scheduling.references import (
    rename_deployment_references,
)
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationDriverVersionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeClusterRepository,
    FakeDeployedServiceRepository,
    FakeDeploymentRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


def _term(deployment_name: str) -> dict:
    return {
        "topology_key": "kubernetes.io/hostname",
        "deployment_ref": {"deployment_name": deployment_name},
    }


def _anti_affinity_naming(deployment_name: str) -> dict:
    return {"scheduling": {"pod_anti_affinity": {"required": [_term(deployment_name)]}}}


class TestRenameDeploymentReferences:
    def test_renames_required_and_preferred_terms_of_both_pod_kinds(self) -> None:
        config = {
            "env_vars": {"FOO": "bar"},
            "scheduling": {
                "pod_affinity": {
                    "required": [_term("api")],
                    "preferred": [{"weight": 10, "term": _term("api")}],
                },
                "pod_anti_affinity": {
                    "preferred": [{"weight": 50, "term": _term("api")}],
                },
            },
        }

        renamed = rename_deployment_references(config, "api", "api-v2")

        assert renamed == {
            "env_vars": {"FOO": "bar"},
            "scheduling": {
                "pod_affinity": {
                    "required": [_term("api-v2")],
                    "preferred": [{"weight": 10, "term": _term("api-v2")}],
                },
                "pod_anti_affinity": {
                    "preferred": [{"weight": 50, "term": _term("api-v2")}],
                },
            },
        }
        assert config["scheduling"]["pod_affinity"]["required"] == [_term("api")], (
            "The input config must not be changed"
        )

    def test_keeps_terms_that_name_another_deployment_or_select_otherwise(
        self,
    ) -> None:
        by_id = {
            "topology_key": "kubernetes.io/hostname",
            "deployment_ref": {"deployment_id": str(uuid4())},
        }
        by_label = {
            "topology_key": "kubernetes.io/hostname",
            "label_selector": {"match_labels": {"app": "api"}},
        }
        config = {
            "scheduling": {
                "pod_affinity": {"required": [_term("api"), _term("db"), by_id]},
                "pod_anti_affinity": {"required": [by_label]},
            }
        }

        renamed = rename_deployment_references(config, "api", "api-v2")

        assert renamed is not None
        assert renamed["scheduling"]["pod_affinity"]["required"] == [
            _term("api-v2"),
            _term("db"),
            by_id,
        ]
        assert renamed["scheduling"]["pod_anti_affinity"] == {"required": [by_label]}

    @pytest.mark.parametrize(
        "config",
        [
            None,
            {},
            {"env_vars": {"FOO": "bar"}},
            {"scheduling": {"runtime_class": "kata"}},
            _anti_affinity_naming("db"),
        ],
    )
    def test_returns_none_when_no_term_names_the_old_name(
        self, config: dict | None
    ) -> None:
        assert rename_deployment_references(config, "api", "api-v2") is None


class _CopyingDeploymentRepository(FakeDeploymentRepository):
    """Returns copies, as a database does, so an unsaved rename is not visible to lookups."""

    async def find(self, id: UUID) -> Deployment | None:
        found = await super().find(id)
        return found.model_copy(deep=True) if found else None

    async def get_by_name(
        self, name: str, environment_id: UUID, *, include_deleted: bool = False
    ) -> Deployment | None:
        found = await super().get_by_name(
            name, environment_id, include_deleted=include_deleted
        )
        return found.model_copy(deep=True) if found else None

    async def find_all_by_environment(
        self, environment_id: UUID, *, include_deleted: bool = False
    ) -> list[Deployment]:
        found = await super().find_all_by_environment(
            environment_id, include_deleted=include_deleted
        )
        return [d.model_copy(deep=True) for d in found]


def _make_uow() -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationDriverVersionRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        deployed_services=FakeDeployedServiceRepository(),
        deployments=_CopyingDeploymentRepository(),
        application_drivers=FakeApplicationRepository(),
    )


async def _fake_apply_state(
    deployment,
    current_instance,
    uow,
    task_type,
    started_by_step_id=None,  # noqa: ANN001
):
    stub = Task.create(
        type=task_type,
        deployment_id=deployment.id,
        started_by_step_id=started_by_step_id,
    )
    await uow.tasks.save(stub)
    return stub


async def _seed(uow: FakeUnitOfWork) -> SimpleNamespace:
    """Seed an environment whose rules name ``api``, and a deployment elsewhere that names ``api``.

    * the environment keeps the pods of every deployment away from ``api``'s;
    * ``api`` keeps its pods away from each other;
    * ``worker`` prefers ``api``'s nodes and keeps away from ``db``'s pods.
    """
    from styrmin_backend.db.models import (
        ApplicationDriver,
        ApplicationDriverVersion,
        Cluster,
        Environment,
        HelmChart,
        HelmRepository,
    )

    cluster = Cluster(name="test-cluster")
    await uow.clusters.create(cluster)
    environment = Environment(
        name="test-env", cluster_id=cluster.id, config=_anti_affinity_naming("api")
    )
    await uow.environments.create(environment)
    other_environment = Environment(name="other-env", cluster_id=cluster.id)
    await uow.environments.create(other_environment)

    helm_repo = HelmRepository(url="https://charts.example.com")
    await uow.helm_repositories.create(helm_repo)
    helm_chart = HelmChart(
        name="test-chart",
        version="1.0.0",
        values_template="",
        repository_id=helm_repo.id,
    )
    await uow.helm_charts.create(helm_chart)
    app_driver = ApplicationDriver(name="test-app")
    adv = ApplicationDriverVersion(
        id=uuid4(),
        version="1.0.0",
        application_supported_versions=">=1.0.0,<2.0.0",
        helm_chart_id=helm_chart.id,
        source_type="git",
        source_repository="https://github.com/test/repo",
        source_branch="main",
        source_path=None,
        application_driver_id=app_driver.id,
        services=[],
        component_configs=[],
    )
    adv.application_driver = app_driver
    await uow.application_driver_versions.create(adv)
    app_driver.versions.insert(0, adv)
    await uow.application_drivers.create(app_driver)

    def _deployment(name: str, config: dict, environment_id: UUID) -> Deployment:
        deployment = Deployment.create(
            application_version="1.0.0",
            application_driver_version_id=adv.id,
            environment_id=environment_id,
            created_by_user_id=uuid4(),
            config=config,
            name=name,
        )
        # Scheduling rules resolve per component, so each deployment needs one.
        deployment.add_component(
            Component.create(
                name="server", config={"identifier": {"label": {"app": name}}}
            )
        )
        return deployment

    api = _deployment("api", _anti_affinity_naming("api"), environment.id)
    worker = _deployment(
        "worker",
        {
            "scheduling": {
                "pod_affinity": {"preferred": [{"weight": 50, "term": _term("api")}]},
                "pod_anti_affinity": {"required": [_term("db")]},
            }
        },
        environment.id,
    )
    db = _deployment("db", {}, environment.id)
    elsewhere = _deployment(
        "elsewhere", _anti_affinity_naming("api"), other_environment.id
    )
    for deployment in (api, worker, db, elsewhere):
        await uow.deployments.save(deployment)
    for deployment in (api, worker, db):
        instance = await generate_instance_from_deployment(
            deployment=deployment, uow=uow
        )
        deployment.set_active_instance(instance=instance)
        deployment.set_status(DeploymentState.RUNNING)
        await uow.instances.create(instance)
        await uow.deployments.save(deployment)
    return SimpleNamespace(
        environment=environment, api=api, worker=worker, elsewhere=elsewhere
    )


async def _assert_rules_name(uow: FakeUnitOfWork, seeded: SimpleNamespace) -> None:
    """Every rule of the environment names ``api-v2``; the other environment still names ``api``."""
    worker = await uow.deployments.find(seeded.worker.id)
    elsewhere = await uow.deployments.find(seeded.elsewhere.id)
    assert worker is not None and elsewhere is not None

    assert seeded.environment.config == _anti_affinity_naming("api-v2")
    assert worker.config == {
        "scheduling": {
            "pod_affinity": {"preferred": [{"weight": 50, "term": _term("api-v2")}]},
            "pod_anti_affinity": {"required": [_term("db")]},
        }
    }
    assert elsewhere.config == _anti_affinity_naming("api"), (
        "A rule resolves in its own environment, so another environment keeps the name"
    )

    # The next reconcile of ``worker`` still finds the renamed deployment.
    instance = await generate_instance_from_deployment(deployment=worker, uow=uow)
    assert instance.context.components is not None
    scheduling = instance.context.components.root["server"].scheduling
    assert scheduling is not None
    pod_affinity = scheduling.config.pod_affinity
    assert pod_affinity is not None
    selector = pod_affinity.preferred[0].term.label_selector
    assert selector is not None
    assert selector.match_labels == {"styrmin/deployment_id": str(seeded.api.id)}


@pytest.mark.asyncio
@patch("styrmin_backend.services.deployment.apply_state", new_callable=AsyncMock)
async def test_update_deployment_rename_rewrites_the_rules_that_name_it(
    mock_apply_state: AsyncMock,
) -> None:
    uow = _make_uow()
    mock_apply_state.side_effect = _fake_apply_state
    seeded = await _seed(uow)

    async with uow:
        await update_deployment(
            deployment_id=seeded.api.id, uow=uow, deployment_name="api-v2"
        )

    api = await uow.deployments.find(seeded.api.id)
    assert api is not None
    assert api.name == "api-v2"
    assert api.config == _anti_affinity_naming("api-v2"), (
        "The renamed deployment's own rule must follow the rename"
    )
    await _assert_rules_name(uow, seeded)


@pytest.mark.asyncio
@patch("styrmin_backend.services.deployment.apply_state", new_callable=AsyncMock)
async def test_update_deployment_rename_rewrites_the_old_name_in_a_submitted_config(
    mock_apply_state: AsyncMock,
) -> None:
    uow = _make_uow()
    mock_apply_state.side_effect = _fake_apply_state
    seeded = await _seed(uow)

    async with uow:
        await update_deployment(
            deployment_id=seeded.api.id,
            uow=uow,
            deployment_name="api-v2",
            deployment_config={"env_vars": {"FOO": "bar"}}
            | _anti_affinity_naming("api"),
        )

    api = await uow.deployments.find(seeded.api.id)
    assert api is not None
    assert api.config == {"env_vars": {"FOO": "bar"}} | _anti_affinity_naming("api-v2")


@pytest.mark.asyncio
@patch("styrmin_backend.services.deployment.apply_state", new_callable=AsyncMock)
async def test_update_deployment_version_rename_rewrites_the_rules_that_name_it(
    mock_apply_state: AsyncMock,
) -> None:
    uow = _make_uow()
    mock_apply_state.side_effect = _fake_apply_state
    seeded = await _seed(uow)

    # The environment's rule applies to ``api`` too, so generating its new
    # instance looks up "api-v2" before the call returns.
    async with uow:
        await update_deployment_version(
            deployment_id=seeded.api.id,
            version="1.0.0",
            uow=uow,
            deployment_name="api-v2",
        )

    api = await uow.deployments.find(seeded.api.id)
    assert api is not None
    assert api.name == "api-v2"
    assert api.config == _anti_affinity_naming("api-v2")
    await _assert_rules_name(uow, seeded)
