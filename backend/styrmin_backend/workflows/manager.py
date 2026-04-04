from typing import Any, Literal
from uuid import UUID

from prefect import flow, task
from prefect.client.orchestration import PrefectClient, get_client
from prefect.client.schemas.actions import WorkPoolCreate
from prefect.client.schemas.filters import DeploymentFilter, DeploymentFilterTags
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
    ) -> None:
        """Register a user action in the Prefect catalogue."""
        # Add tags to the workflow
        workflow.tags.append(f"application/{application}")
        workflow.tags.append(f"version/{version}")
        workflow.tags.append(f"hook/{hook.value}")
        workflow.tags.append(f"mode/{mode}")
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
    ) -> UUID | None:
        """Get the workflow ID for a specific user action in the Prefect deployments."""
        async with get_client() as client:
            deployments = await client.read_deployments(
                deployment_filter=DeploymentFilter(
                    tags=DeploymentFilterTags(
                        all_=[
                            f"application/{application}",
                            f"hook/{hook.value}",
                            f"mode/{mode}",
                            f"version/{version}",
                        ]
                    )
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
