from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from prefect import flow, task
from prefect.client.orchestration import PrefectClient, get_client
from prefect.client.schemas.actions import WorkPoolCreate
from prefect.client.schemas.filters import DeploymentFilter, DeploymentFilterTags
from prefect.client.schemas.objects import StateType
from prefect.client.schemas.sorting import DeploymentSort
from prefect.events.actions import ChangeFlowRunState
from prefect.events.schemas.automations import AutomationCore, EventTrigger, Posture
from prefect.events.schemas.events import ResourceSpecification
from prefect.exceptions import ObjectAlreadyExists
from prefect.logging import get_run_logger
from prefect.settings import get_current_settings
from prefect_github import GitHubCredentials
from prefect.cache_policies import NO_CACHE

from styrmin_backend import config
from styrmin_backend.services.driver.driver_directory import driver_directory_digest
from styrmin_backend.services.driver.models.resources.actions import HookKind
from styrmin_backend.services.workflow.worker import StyrminWorkflowExecutor
from styrmin_backend.workflows.bsl_credentials import (
    BslCredentials,
    delete_bsl_credentials,
    save_bsl_credentials,
)
from styrmin_backend.workflows.catalogue import PrefectCatalogue
from styrmin_backend.workflows.constants import WorkflowType
from styrmin_backend.workflows.models import (
    PrefectAction,
    PrefectWorkPool,
    WorkflowDefinition,
    WorkflowInfo,
)

# Tag of a user action's deployment whose driver version has a driver directory.
DIRECTORY_TAG_PREFIX = "directory/"


class PrefectManager:
    def __init__(
        self, catalogue: PrefectCatalogue, workflow_executor: StyrminWorkflowExecutor
    ) -> None:
        self.catalogue = catalogue
        self.executor = workflow_executor

    async def run_action(
        self,
        action: PrefectAction,
        parameters: dict[str, Any] | None = None,
    ) -> WorkflowInfo:
        """Run a specific action."""
        workflow = self.catalogue.get_workflow_definition(action)
        return await self.executor.submit_workflow(
            workflow=workflow,  # type: ignore[arg-type]
            parameters=parameters or {},
        )

    async def get_action_deployment_id(self, action: PrefectAction) -> UUID | None:
        """Get the workflow ID for a specific action in the Prefect deployments."""
        async with get_client() as client:
            deployments = await client.read_deployments(
                deployment_filter=DeploymentFilter(
                    tags=DeploymentFilterTags(all_=[action.to_tag()])
                ),
            )
            if not deployments:
                return None
            return deployments[0].id

    async def register_user_action(
        self,
        workflow: WorkflowDefinition,
        application: str,
        version: str,
        hook: HookKind,
        mode: Literal["pre", "core", "post"],
        fingerprint: str | None = None,
        *,
        driver_directory: str | None,
    ) -> None:
        """Register a user action in the Prefect catalogue.

        Spec 013 — when ``fingerprint`` is provided (the first 7 chars of
        the driver row's ``source_commit_sha`` or ``content_hash``), it is
        included as a ``fingerprint/{short}`` tag. This keeps two distinct
        same-version reloads (different content / commit) from clobbering
        each other's deployment: deployments are keyed on
        (application, version, hook, mode, fingerprint), and execution-time
        lookups in :meth:`get_user_action_deployment_id` must pass the same
        fingerprint so older instances keep resolving to their original
        workflow.

        The application and the fingerprint also name the Prefect deployment
        (``<workflow> (<application>@<fingerprint>)``): Prefect upserts on
        ``(flow, name)``, so a shared name would let another driver (#373) or
        a reload of the same driver (#375) overwrite this deployment.

        Spec 028 — when ``driver_directory`` is set (the driver version was
        loaded from a driver directory of its repository), the deployment
        gets the tag ``directory/<driver_directory>`` and the name ends with
        the 12-character digest of the driver directory
        (``<workflow> (<application>@<fingerprint> <digest>)``), so two
        driver versions loaded from one commit keep separate deployments.
        Prefect refuses ``/`` in deployment names, hence the digest. A load
        from the repository root (``None``) keeps the name and tags above.
        ``driver_directory`` has no default, so every caller states it.
        """
        # Add tags to the workflow
        workflow.tags.append(f"application/{application}")
        workflow.tags.append(f"version/{version}")
        workflow.tags.append(f"hook/{hook.value}")
        workflow.tags.append(f"mode/{mode}")
        if fingerprint:
            workflow.tags.append(f"fingerprint/{fingerprint}")
            label = f"{application}@{fingerprint}"
        else:
            label = application
        if driver_directory:
            workflow.tags.append(f"{DIRECTORY_TAG_PREFIX}{driver_directory}")
            label = f"{label} {driver_directory_digest(driver_directory)}"
        workflow.deployment_name = f"{workflow.name} ({label})"
        async with get_client(sync_client=False) as client:
            await workflow.save(
                client=client,
                work_pool=self.catalogue.get_work_pool(PrefectWorkPool.USER_WORK_POOL),
            )

    async def get_user_action_deployment_id(
        self,
        application: str,
        version: str,
        hook: HookKind,
        mode: Literal["pre", "core", "post"],
        fingerprint: str | None = None,
        *,
        driver_directory: str | None,
    ) -> UUID | None:
        """Get the workflow ID for a specific user action in the Prefect deployments.

        Spec 013 — ``fingerprint`` (the short form of the driver row's
        provenance fingerprint) must match the value used at registration
        time. ``None`` is preserved for legacy rows whose driver was
        registered before the fingerprint tag existed; for those rows the
        lookup omits the tag and continues to find the historical
        deployment.

        Spec 028 — ``driver_directory`` must match the value used at
        registration time, and has no default. When set, the lookup also requires the tag
        ``directory/<driver_directory>``. When ``None`` (a load from the
        repository root, or a local driver), deployments with any
        ``directory/`` tag are dropped, so a root driver version never runs
        another driver directory's action: Prefect's tag filter cannot
        exclude a tag, so the drop happens here.
        """
        tags = [
            f"application/{application}",
            f"hook/{hook.value}",
            f"mode/{mode}",
            f"version/{version}",
        ]
        if fingerprint:
            tags.append(f"fingerprint/{fingerprint}")
        if driver_directory:
            tags.append(f"{DIRECTORY_TAG_PREFIX}{driver_directory}")
        async with get_client() as client:
            # Newest first: a pinned registration must outrank an older
            # branch-tip deployment carrying the same tags.
            deployments = await client.read_deployments(
                deployment_filter=DeploymentFilter(
                    tags=DeploymentFilterTags(all_=tags)
                ),
                sort=DeploymentSort.CREATED_DESC,
            )
        if not driver_directory:
            deployments = [
                deployment
                for deployment in deployments
                if not any(
                    tag.startswith(DIRECTORY_TAG_PREFIX) for tag in deployment.tags
                )
            ]
        if not deployments:
            return None
        return deployments[0].id

    async def register_token(self, namespace: str, token: str) -> None:
        """Register a token in the Prefect catalogue."""
        await GitHubCredentials(token=token).save(
            name=f"{namespace}-github-token", overwrite=True
        )

    async def save_bsl_credentials(
        self, bsl_id: UUID, access_key_id: str, secret_access_key: str
    ) -> None:
        """Save the S3 keys of a backup storage location for the sync-bsl flows."""
        await save_bsl_credentials(
            str(bsl_id),
            BslCredentials(
                access_key_id=access_key_id, secret_access_key=secret_access_key
            ),
        )

    async def delete_bsl_credentials(self, bsl_id: UUID) -> None:
        """Delete the saved S3 keys of a backup storage location."""
        await delete_bsl_credentials(str(bsl_id))

    @task(
        name="task-manager-setup-worker-pools",
        task_run_name="Setup Worker pools",
        cache_policy=NO_CACHE,
    )
    async def setup_work_pools(self, client: PrefectClient) -> None:
        log = get_run_logger()
        for work_pool in self.catalogue.work_pools:
            wp = WorkPoolCreate(
                name=work_pool.name,
                type=work_pool.worker_type  # type: ignore[attr-defined]
                or config.SETTINGS.workflow.default_worker_type,
                description=work_pool.description,  # type: ignore[attr-defined]
                base_job_template=work_pool.base_job_template or {},  # type: ignore[attr-defined]
            )
            try:
                await client.create_work_pool(work_pool=wp, overwrite=True)
                log.info(f"Work pool {work_pool.name} created successfully ... ")
            except ObjectAlreadyExists:
                log.warning(f"Work pool {work_pool.name} already present ")

    @task(
        name="task-manager-setup-deployments",
        task_run_name="Setup Deployments",
        cache_policy=NO_CACHE,
    )
    async def setup_deployments(self, client: PrefectClient) -> None:
        log = get_run_logger()

        workpool_mapping = {
            WorkflowType.INTERNAL: PrefectWorkPool.STYRMIN_WORK_POOL,
            WorkflowType.USER: PrefectWorkPool.USER_WORK_POOL,
        }

        for workflow in self.catalogue.workflows:
            workpool = workpool_mapping.get(workflow.type, None)
            if workpool is None:
                log.error(f"Workflow {workflow.name} has no work pool assigned")
                continue

            await workflow.save(
                client=client, work_pool=self.catalogue.get_work_pool(workpool)
            )
            log.info(f"Flow {workflow.name}, created successfully ... ")

    @task(
        name="task-manager-setup-zombie-flow-run-automation",
        task_run_name="Setup Zombie Flow Run Automation",
        cache_policy=NO_CACHE,
    )
    async def setup_zombie_flow_run_automation(self, client: PrefectClient) -> None:
        """Register the Automation that crashes zombie flow runs (#312).

        A worker process that dies while a flow run's subprocess is still
        alive recovers correctly on its own (the surviving parent observes
        the subprocess's non-zero exit and proposes ``Crashed``). But if the
        *worker process itself* dies -- an OOM-killed pod, a
        ``kubectl rollout restart``, a node eviction -- nothing else in
        Prefect ever notices; the flow run stays claimed by the dead worker
        in RUNNING/PENDING forever. Confirmed by direct reproduction.

        Prefect flow runs emit heartbeat events by default since 3.6.22
        (``PREFECT_FLOWS_HEARTBEAT_FREQUENCY``, 180s default here). This
        Automation is Prefect's own documented mechanism for reacting to
        missed heartbeats -- see
        https://docs.prefect.io/v3/advanced/detect-zombie-flows -- and
        works against a self-hosted server (no Prefect Cloud required).

        The detection window (``within``) must be a multiple of the actual
        configured heartbeat frequency -- Prefect's own docs recommend 3x to
        avoid false positives, and a window shorter than one full heartbeat
        interval flags every in-flight flow run as unresponsive, since a
        healthy run's heartbeats are naturally spaced that far apart. A
        first version of this shipped with a hardcoded 90s window (copied
        from Prefect's docs example, which assumes a 30s heartbeat interval,
        not this codebase's 180s default) and crashed real, healthy
        long-running flows in CI (backup/restore, infrahub deploys) --
        reading the interval from settings instead of hardcoding it prevents
        this class of bug from recurring if the setting ever changes.

        Idempotent: upserts by name so repeated calls (every server start)
        don't create duplicate Automations.
        """
        log = get_run_logger()
        name = "Crash zombie flow runs"
        heartbeat_frequency = get_current_settings().flows.heartbeat_frequency or 180
        detection_window = timedelta(seconds=heartbeat_frequency * 3)
        automation = AutomationCore(
            name=name,
            description="Marks flow runs Crashed after their worker stops sending heartbeats (#312).",
            trigger=EventTrigger(
                after={"prefect.flow-run.heartbeat"},
                expect={"prefect.flow-run.*"},
                match=ResourceSpecification(
                    {"prefect.resource.id": ["prefect.flow-run.*"]}
                ),
                for_each={"prefect.resource.id"},
                posture=Posture.Proactive,
                threshold=1,
                within=detection_window,
            ),
            actions=[
                ChangeFlowRunState(
                    state=StateType.CRASHED,
                    message=(
                        "Flow run's worker stopped sending heartbeats "
                        "(worker likely died mid-execution). Reconciled by "
                        f"the {name!r} Automation. See #312."
                    ),
                )
            ],
        )

        existing = await client.read_automations_by_name(name=name)
        if existing:
            await client.update_automation(
                automation_id=existing[0].id, automation=automation
            )
            log.info(f"Automation {name!r} already present, updated ... ")
        else:
            await client.create_automation(automation=automation)
            log.info(f"Automation {name!r} created successfully ... ")

    @staticmethod
    @task(name="task-manager-setup-blocks", task_run_name="Setup Blocks")
    async def setup_blocks() -> None:
        log = get_run_logger()

        # Save github credentials
        # TODO: Implement github credentials store
        await GitHubCredentials(token=config.SETTINGS.agent_code.token).save(
            name="core-github-token", overwrite=True
        )
        log.info("GitHub credentials saved successfully ... ")

    @flow(name="task-manager-setup", flow_run_name="Setup Task Manager")
    async def initialize(self) -> None:
        async with get_client(sync_client=False) as client:
            await self.setup_blocks()
            await self.setup_work_pools(client=client)  # type: ignore  # Prefect Task.__call__ overload resolution
            await self.setup_deployments(client=client)  # type: ignore  # Prefect Task.__call__ overload resolution
            await self.setup_zombie_flow_run_automation(client=client)  # type: ignore  # Prefect Task.__call__ overload resolution
