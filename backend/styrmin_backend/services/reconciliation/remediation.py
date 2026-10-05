import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import Type
from uuid import UUID

from fast_depends import Depends, inject
from loguru import logger
from prefect.client.schemas.objects import FlowRun

from styrmin_backend.agent.tasks.utils import (
    api_token_job_variables,
    run_deployment_or_fail,
)

from pydantic import BaseModel

from styrmin_backend.domain.models import Instance
from styrmin_backend.services.driver.labels import short_fingerprint
from styrmin_backend.services.driver.models.resources.actions import HookKind
from styrmin_backend.services.reconciliation.diffs.diffs import (
    ApplicationDriverVersionChange,
    ApplicationVersionChange,
    ContextChange,
    Diff,
    DiffReport,
    InstanceCreation,
    InstanceDeletion,
    InstanceUpdate,
)
from styrmin_backend.services.reconciliation.exceptions import ReconciliationError
from styrmin_backend.services.unit_of_work import UnitOfWork
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import PrefectAction


class RemediationType(str, Enum):
    """Enum for remediation types."""

    CREATE_INSTANCE = "create_instance"
    DELETE_INSTANCE = "delete_instance"
    UPDATE_INSTANCE = "update_instance"
    UPGRADE_INSTANCE = "upgrade_instance"
    DOWNGRADE_INSTANCE = "downgrade_instance"


class Remediation(BaseModel):
    instance: Instance
    flow_id: UUID
    parameters: dict
    type: RemediationType

    async def apply(self, api_token: str | None = None) -> FlowRun:
        """Apply the remediation; ``api_token`` reaches the driver actions it runs."""
        logger.info(
            "Applying remediation: type={} instance_id={} flow_id={}",
            self.type,
            self.instance.id,
            self.flow_id,
        )

        # Run the orchestration workflow
        flow_info = await run_deployment_or_fail(
            name=self.flow_id,
            parameters=self.parameters,
            job_variables=api_token_job_variables(api_token),
        )

        logger.info(
            "Remediation flow started: type={} flow_run_id={} state={}",
            self.type,
            flow_info.id,
            flow_info.state_name,
        )

        return flow_info


class RemediationStrategy(ABC):
    """Abstract base class for remediation strategies."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    @abstractmethod
    @inject
    async def execute(
        self, diff: Diff, prefect_manager: PrefectManager = Depends(get_manager)
    ) -> Remediation | None:
        """Generate remediation steps based on the provided diff report."""
        pass


class InstanceCreationStrategy(RemediationStrategy):
    @inject
    async def execute(
        self, diff: Diff, prefect_manager: PrefectManager = Depends(get_manager)
    ) -> Remediation | None:
        if not isinstance(diff, InstanceCreation):
            return None

        # Get the driver version
        driver_version = await self.uow.application_driver_versions.get(
            id=diff.instance.application_driver_version_id
        )
        assert driver_version is not None, "Driver version not found"

        # Get the application
        application = await self.uow.application_drivers.get(
            id=driver_version.application_driver_id
        )
        assert application is not None, "Application not found"

        create_instance_flow = await prefect_manager.get_action_deployment_id(
            action=PrefectAction.CREATE_INSTANCE,
        )
        assert create_instance_flow is not None, (
            "Create instance flow deployment not found"
        )

        # The CRD flow only needs pre/post hooks — the operator handles
        # HelmRelease creation and utility resource management.
        # Spec 013 — pass the row-bound fingerprint so we resolve the
        # workflow registered against this specific driver version, not
        # whatever last-write-wins for the (application, version) tuple.
        instance_fingerprint = short_fingerprint(
            content_hash=driver_version.content_hash,
            source_commit_sha=driver_version.source_commit_sha,
        )
        prehook, posthook = await asyncio.gather(
            prefect_manager.get_user_action_deployment_id(
                application=application.name,
                hook=HookKind.SETUP,
                mode="pre",
                version=driver_version.application_supported_versions,
                fingerprint=instance_fingerprint,
            ),
            prefect_manager.get_user_action_deployment_id(
                application=application.name,
                hook=HookKind.SETUP,
                mode="post",
                version=driver_version.application_supported_versions,
                fingerprint=instance_fingerprint,
            ),
        )

        # Check if the deployment is internal (e.g., ingress controller)
        deployment = await self.uow.deployments.get(id=diff.instance.deployment_id)
        is_internal = deployment.internal if deployment else False

        return Remediation(
            type=RemediationType.CREATE_INSTANCE,
            instance=diff.instance,
            flow_id=create_instance_flow,
            parameters={
                "instance": diff.instance,
                "prehook": prehook,
                "posthook": posthook,
                "internal": is_internal,
            },
        )


class InstanceDeletionStrategy(RemediationStrategy):
    @inject
    async def execute(
        self, diff: Diff, prefect_manager: PrefectManager = Depends(get_manager)
    ) -> Remediation | None:
        if not isinstance(diff, InstanceDeletion):
            return None
        raise NotImplementedError(
            "Instance deletion remediation strategy is not implemented yet."
        )


class InstanceUpdateStrategy(RemediationStrategy):
    @inject
    async def execute(
        self, diff: Diff, prefect_manager: PrefectManager = Depends(get_manager)
    ) -> Remediation | None:
        if not isinstance(diff, InstanceUpdate):
            return None

        logger.info(
            "Processing instance update: instance_id={} diffs={}",
            diff.instance.id,
            [type(entry).__name__ for entry in diff.diffs],
        )

        # Check if a version change is present (upgrade takes priority over update)
        has_version_change = any(
            isinstance(entry, ApplicationVersionChange) for entry in diff.diffs
        )

        if has_version_change:
            logger.info("Version change detected, attempting upgrade path")
            upgrade_remediation = await self._handle_upgrade(diff, prefect_manager)
            if upgrade_remediation is not None:
                return upgrade_remediation
            logger.info("No upgrade hook found, falling back to regular update")

        return await self._handle_update(diff, prefect_manager)

    async def _handle_upgrade(
        self, diff: InstanceUpdate, prefect_manager: PrefectManager
    ) -> Remediation | None:
        """Handle a version change by looking up upgrade hooks from the driver."""
        # Get the driver version (from the NEW instance)
        driver_version = await self.uow.application_driver_versions.get(
            id=diff.instance.application_driver_version_id
        )
        assert driver_version is not None, "Driver version not found"

        # Get the application
        application = await self.uow.application_drivers.get(
            id=driver_version.application_driver_id
        )
        assert application is not None, "Application not found"

        logger.info(
            "Looking up upgrade hook: application={} driver_version={} supported_versions={}",
            application.name,
            driver_version.id,
            driver_version.application_supported_versions,
        )

        # Spec 013 — bind lookups to the row's provenance fingerprint so
        # an older instance whose driver was reloaded under a new commit
        # still resolves to its original workflow registration.
        upgrade_fingerprint = short_fingerprint(
            content_hash=driver_version.content_hash,
            source_commit_sha=driver_version.source_commit_sha,
        )

        # Look up the upgrade core hook from Prefect
        upgrade_hook = await prefect_manager.get_user_action_deployment_id(
            application=application.name,
            hook=HookKind.UPGRADE,
            mode="core",
            version=driver_version.application_supported_versions,
            fingerprint=upgrade_fingerprint,
        )

        # If no upgrade core hook is defined, fall back to regular update
        if upgrade_hook is None:
            logger.info(
                "No upgrade core hook defined for application={}, will use regular update",
                application.name,
            )
            return None

        logger.info(
            "Upgrade core hook found: upgrade_hook={}, resolving upgrade flows and pre/post hooks",
            upgrade_hook,
        )

        # The CRD flow only needs the upgrade hook and pre/post hooks —
        # the operator handles HelmRelease and utility resource management.
        upgrade_instance_flow, prehook, posthook = await asyncio.gather(
            prefect_manager.get_action_deployment_id(
                action=PrefectAction.UPGRADE_INSTANCE,
            ),
            prefect_manager.get_user_action_deployment_id(
                application=application.name,
                hook=HookKind.UPGRADE,
                mode="pre",
                version=driver_version.application_supported_versions,
                fingerprint=upgrade_fingerprint,
            ),
            prefect_manager.get_user_action_deployment_id(
                application=application.name,
                hook=HookKind.UPGRADE,
                mode="post",
                version=driver_version.application_supported_versions,
                fingerprint=upgrade_fingerprint,
            ),
        )
        assert upgrade_instance_flow is not None, (
            "Upgrade instance flow deployment not found"
        )

        logger.info(
            "Upgrade remediation ready: application={} target_version={} prehook={} posthook={}",
            application.name,
            diff.instance.application_version,
            prehook is not None,
            posthook is not None,
        )

        return Remediation(
            type=RemediationType.UPGRADE_INSTANCE,
            instance=diff.instance,
            flow_id=upgrade_instance_flow,
            parameters={
                "instance": diff.instance,
                "upgrade_hook": upgrade_hook,
                "target_version": diff.instance.application_version,
                "prehook": prehook,
                "posthook": posthook,
            },
        )

    async def _handle_update(
        self, diff: InstanceUpdate, prefect_manager: PrefectManager
    ) -> Remediation | None:
        """Handle a regular update (config change, no version change)."""
        for diff_entry in diff.diffs:
            if isinstance(
                diff_entry,
                (
                    ApplicationVersionChange,
                    ApplicationDriverVersionChange,
                    ContextChange,
                ),
            ):
                logger.info(
                    "Handling regular update for instance_id={} triggered by {}",
                    diff.instance.id,
                    type(diff_entry).__name__,
                )

                # The CRD flow only needs the instance — the operator
                # handles HelmRelease and utility resource reconciliation.
                update_instance_flow = await prefect_manager.get_action_deployment_id(
                    action=PrefectAction.UPDATE_INSTANCE,
                )
                assert update_instance_flow is not None, (
                    "Update instance flow deployment not found"
                )

                return Remediation(
                    type=RemediationType.UPDATE_INSTANCE,
                    instance=diff.instance,
                    flow_id=update_instance_flow,
                    parameters={
                        "instance": diff.instance,
                    },
                )

        logger.info(
            "No actionable diff entries found for instance_id={}", diff.instance.id
        )
        return None


class Remediator:
    """Generates remediation for provided diffs."""

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow
        self.strategies: dict[Type[Diff], RemediationStrategy] = {
            InstanceCreation: InstanceCreationStrategy(uow=self.uow),
            InstanceDeletion: InstanceDeletionStrategy(uow=self.uow),
            InstanceUpdate: InstanceUpdateStrategy(uow=self.uow),
        }

    async def _handle_diff(self, diff: Diff) -> Remediation:
        strategy = self.strategies.get(type(diff), None)
        if strategy is None:
            raise ValueError(f"No strategy found for diff type: {type(diff)}")

        remediation = await strategy.execute(diff)
        if remediation:
            return remediation

        raise ReconciliationError(f"No applicable remediation found for diff: {diff}")

    async def generate_remediation(self, diff_report: DiffReport) -> Remediation | None:
        """Process the provided diffs and generate remediation steps."""
        if diff_report.diff is None:
            return None
        remediation = await self._handle_diff(diff_report.diff)
        logger.debug(f"Generated remediation: {remediation.type}")

        return remediation
