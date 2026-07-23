from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from prefect import flow, task
from prefect.client.orchestration import PrefectClient, get_client
from prefect.client.schemas.actions import WorkPoolCreate
from prefect.client.schemas.filters import DeploymentFilter, DeploymentFilterTags
from prefect.client.schemas.objects import StateType
from prefect.events.actions import ChangeFlowRunState
from prefect.events.schemas.automations import AutomationCore, EventTrigger, Posture
from prefect.events.schemas.events import ResourceSpecification
from prefect.exceptions import ObjectAlreadyExists
from prefect.logging import get_run_logger
from prefect_github import GitHubCredentials
from prefect.cache_policies import NO_CACHE

from styrmin_backend import config
from styrmin_backend.services.driver.models.resources.actions import HookKind
from styrmin_backend.services.workflow.worker import StyrminWorkflowExecutor
from styrmin_backend.workflows.catalogue import PrefectCatalogue
from styrmin_backend.workflows.constants import WorkflowType
from styrmin_backend.workflows.models import (
    PrefectAction,
    PrefectWorkPool,
    WorkflowDefinition,
    WorkflowInfo,
)


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
        """
        # Add tags to the workflow
        workflow.tags.append(f"application/{application}")
        workflow.tags.append(f"version/{version}")
        workflow.tags.append(f"hook/{hook.value}")
        workflow.tags.append(f"mode/{mode}")
        if fingerprint:
            workflow.tags.append(f"fingerprint/{fingerprint}")
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
    ) -> UUID | None:
        """Get the workflow ID for a specific user action in the Prefect deployments.

        Spec 013 — ``fingerprint`` (the short form of the driver row's
        provenance fingerprint) must match the value used at registration
        time. ``None`` is preserved for legacy rows whose driver was
        registered before the fingerprint tag existed; for those rows the
        lookup omits the tag and continues to find the historical
        deployment.
        """
        tags = [
            f"application/{application}",
            f"hook/{hook.value}",
            f"mode/{mode}",
            f"version/{version}",
        ]
        if fingerprint:
            tags.append(f"fingerprint/{fingerprint}")
        async with get_client() as client:
            deployments = await client.read_deployments(
                deployment_filter=DeploymentFilter(
                    tags=DeploymentFilterTags(all_=tags)
                ),
            )
            if not deployments:
                return None
            return deployments[0].id

    async def register_token(self, namespace: str, token: str) -> None:
        """Register a token in the Prefect catalogue."""
        await GitHubCredentials(token=token).save(
            name=f"{namespace}-github-token", overwrite=True
        )

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
        (``PREFECT_FLOWS_HEARTBEAT_FREQUENCY``, 180s default). This
        Automation is Prefect's own documented mechanism for reacting to
        missed heartbeats -- see
        https://docs.prefect.io/v3/advanced/detect-zombie-flows -- and
        works against a self-hosted server (no Prefect Cloud required).
        Verified live: catches a worker killed mid-flow-run in ~80s, with
        no dependency on worker-offline detection or a worker restart.

        Idempotent: upserts by name so repeated calls (every server start)
        don't create duplicate Automations.
        """
        log = get_run_logger()
        name = "Crash zombie flow runs"
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
                within=timedelta(seconds=90),
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
