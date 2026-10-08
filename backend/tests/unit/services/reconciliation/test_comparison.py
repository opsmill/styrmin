from uuid import UUID, uuid4

from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_backend.domain.models import Instance, InstanceStatus
from styrmin_backend.services.reconciliation.diffs.comparison import Comparator
from styrmin_backend.services.reconciliation.diffs.diffs import (
    ApplicationVersionChange,
    InstanceCreation,
    InstanceDeletion,
    InstanceUpdate,
)


def _make_context(app_version: str = "1.0.0") -> GlobalContext:
    """Build a minimal GlobalContext for testing."""
    deployment_id = uuid4()
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=deployment_id,
            namespace=f"styrmin-{deployment_id}",
            release_reference=f"styrmin-{deployment_id}",
        ),
        app=ApplicationContext(
            name="test-app",
            version=app_version,
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(),
                    name="test-chart",
                    version="0.1.0",
                    values_template="image:\n  tag: {{ app.version }}",
                ),
                repository=RepositoryInfo(
                    id=uuid4(),
                    url="http://chart-server.local:8080",
                ),
            ),
        ),
    )


def _make_instance(
    application_version: str = "1.0.0",
    context: GlobalContext | None = None,
    deployment_id: UUID | None = None,
    driver_version_id: UUID | None = None,
) -> Instance:
    """Build a minimal Instance for testing."""
    if context is None:
        context = _make_context(app_version=application_version)
    return Instance(
        id=uuid4(),
        name="test-instance",
        application_version=application_version,
        status=InstanceStatus.PENDING,
        deployment_id=deployment_id or uuid4(),
        application_driver_version_id=driver_version_id or uuid4(),
        context=context,
    )


class TestComparatorCompare:
    def test_both_none_returns_no_diff(self) -> None:
        comparator = Comparator(current_instance=None, new_instance=None)
        report = comparator.compare()
        assert report.diff is None
        assert report.raw is None

    def test_current_none_returns_creation(self) -> None:
        new = _make_instance()
        comparator = Comparator(current_instance=None, new_instance=new)
        report = comparator.compare()
        assert isinstance(report.diff, InstanceCreation)
        assert report.diff.instance is new

    def test_new_none_returns_deletion(self) -> None:
        current = _make_instance()
        comparator = Comparator(current_instance=current, new_instance=None)
        report = comparator.compare()
        assert isinstance(report.diff, InstanceDeletion)
        assert report.diff.instance is current

    def test_identical_instances_returns_no_diff(self) -> None:
        """When two instances are identical (same version, context, driver version),
        the comparator should return DiffReport(diff=None)."""
        deployment_id = uuid4()
        driver_version_id = uuid4()
        context = _make_context(app_version="1.0.0")

        current = Instance(
            id=uuid4(),
            name="instance-a",
            application_version="1.0.0",
            status=InstanceStatus.RUNNING,
            deployment_id=deployment_id,
            application_driver_version_id=driver_version_id,
            context=context,
        )
        new = Instance(
            id=uuid4(),
            name="instance-b",
            application_version="1.0.0",
            status=InstanceStatus.PENDING,
            deployment_id=deployment_id,
            application_driver_version_id=driver_version_id,
            context=context,
        )

        comparator = Comparator(current_instance=current, new_instance=new)
        report = comparator.compare()
        assert report.diff is None

    def test_instances_differing_only_in_sequence_have_no_raw_diff(
        self,
    ) -> None:
        """``sequence`` orders StyrminDeployment writes (#386); it is not a change to apply."""
        current = _make_instance().model_copy(update={"sequence": 6})
        new = current.model_copy(update={"id": uuid4(), "sequence": None})

        report = Comparator(current_instance=current, new_instance=new).compare()

        assert report.diff is None
        assert report.raw is None

    def test_version_change_returns_instance_update(self) -> None:
        """When the application version changes, the comparator should return
        an InstanceUpdate with an ApplicationVersionChange diff entry."""
        deployment_id = uuid4()
        driver_version_id = uuid4()

        current = Instance(
            id=uuid4(),
            name="instance-a",
            application_version="1.0.0",
            status=InstanceStatus.RUNNING,
            deployment_id=deployment_id,
            application_driver_version_id=driver_version_id,
            context=_make_context(app_version="1.0.0"),
        )
        new = Instance(
            id=uuid4(),
            name="instance-b",
            application_version="2.0.0",
            status=InstanceStatus.PENDING,
            deployment_id=deployment_id,
            application_driver_version_id=driver_version_id,
            context=_make_context(app_version="2.0.0"),
        )

        comparator = Comparator(current_instance=current, new_instance=new)
        report = comparator.compare()
        assert isinstance(report.diff, InstanceUpdate)
        assert len(report.diff.diffs) > 0

        version_changes = [
            d for d in report.diff.diffs if isinstance(d, ApplicationVersionChange)
        ]
        assert len(version_changes) == 1
        assert version_changes[0].current_value == "1.0.0"
        assert version_changes[0].new_value == "2.0.0"
