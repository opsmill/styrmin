from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from styrmin_backend import config
from styrmin_backend.workflows.utils import (
    load_job_configuration_template,
    load_variables_template,
)

from .constants import WorkflowType
from .models import (
    LocalSourceWorkflowDefinition,
    PrefectAction,
    PrefectWorkPool,
    WorkflowDefinition,
    WorkPoolDefinition,
)


class PrefectCatalogue:
    """A catalogue of Prefect workflows and work pools for the Styrmin system."""

    def __init__(self) -> None:
        config.SETTINGS.initialize_and_exit()

        self.work_pools_registry: dict[PrefectWorkPool, WorkPoolDefinition] = {}
        self.workflows_registry: dict[PrefectAction, WorkflowDefinition] = {}

        self._register_default_work_pools()
        self._register_default_workflows()

    @property
    def work_pools(self) -> Iterable[WorkPoolDefinition]:
        """Get the list of work pools."""
        return list(self.work_pools_registry.values())

    @property
    def workflows(self) -> Iterable[WorkflowDefinition]:
        """Get the list of workflows."""
        return list(self.workflows_registry.values())

    def get_work_pool(self, role: PrefectWorkPool) -> WorkPoolDefinition:
        """Get a work pool by its role."""
        if role not in self.work_pools_registry:
            raise ValueError(f"Work pool {role} not found in the registry.")
        return self.work_pools_registry[role]

    def get_workflow_definition(self, action: PrefectAction) -> WorkflowDefinition:
        """Get a workflow definition by its action."""
        if action not in self.workflows_registry:
            raise ValueError(f"Workflow {action} not found in the registry.")
        return self.workflows_registry[action]

    def add_work_pool(
        self, role: PrefectWorkPool, work_pool: WorkPoolDefinition
    ) -> None:
        """Add a work pool to the registry."""
        if role in self.work_pools_registry:
            raise ValueError(f"Work pool {role} already exists in the registry.")
        self.work_pools_registry[role] = work_pool

    def add_workflow_definition(
        self, action: PrefectAction, workflow: WorkflowDefinition
    ) -> None:
        """Add a workflow definition to the registry."""
        if action in self.workflows_registry:
            raise ValueError(f"Workflow {action} already exists in the registry.")

        # Add action tag to the workflow
        if action.to_tag() not in workflow.tags:
            workflow.tags.append(action.to_tag())

        self.workflows_registry[action] = workflow

    def _register_default_work_pools(self) -> None:
        """Register the default work pools required by the Styrmin system.

        Current work pools:
        - Styrmin work pool: Default pool for internal tasks. Mostly orchestration tasks.
        - User work pool: Default pool for user scoped tasks.
        """
        # Initialize the Styrmin work pool
        self.add_work_pool(
            role=PrefectWorkPool.STYRMIN_WORK_POOL,
            work_pool=WorkPoolDefinition(
                name="styrmin-work-pool",
                description="Default Pool for internal tasks",
                worker_type="process",
            ),
        )

        # Load the job template variables
        job_template_variables = load_variables_template(
            template_path=Path(__file__).parent / "templates" / "variables.json"
        )
        # Set the service account name from the Styrmin config
        job_template_variables["properties"]["service_account_name"]["default"] = (
            config.SETTINGS.kubernetes.service_account
        )
        job_template_variables["properties"]["image"]["default"] = (
            config.SETTINGS.kubernetes.worker_image
        )

        if config.SETTINGS.url:
            job_template_variables["properties"]["env"]["default"][
                "STYRMIN_URL_API"
            ] = config.SETTINGS.url.api_k8s

        # Forward agent poll settings to K8s jobs
        poll_env_vars = {
            "STYRMIN_AGENT_POLL_RETRIES": os.environ.get(
                "STYRMIN_AGENT_POLL_RETRIES", ""
            ),
            "STYRMIN_AGENT_POLL_RETRY_DELAY_SECONDS": os.environ.get(
                "STYRMIN_AGENT_POLL_RETRY_DELAY_SECONDS", ""
            ),
            "STYRMIN_AGENT_POLL_INTERVAL": os.environ.get(
                "STYRMIN_AGENT_POLL_INTERVAL", ""
            ),
        }
        for key, value in poll_env_vars.items():
            if value:
                job_template_variables["properties"]["env"]["default"][key] = value

        # Initialize the User work pool
        self.add_work_pool(
            role=PrefectWorkPool.USER_WORK_POOL,
            work_pool=WorkPoolDefinition(
                name="user-work-pool",
                description="Default Pool for user tasks",
                base_job_template={
                    "variables": job_template_variables,
                    "job_configuration": load_job_configuration_template(
                        template_path=Path(__file__).parent
                        / "templates"
                        / "job_configuration.yaml"
                    ),
                },
            ),
        )

    def _register_default_workflows(self) -> None:
        """Register the default workflows required by the Styrmin system.

        Current workflows:
        - instantiate_application: Workflow to instantiate an application instance.
        - orchestrate_application_setup: Workflow to orchestrate the setup of an application instance.

        """

        self.add_workflow_definition(
            action=PrefectAction.APPLY_STATE,
            workflow=LocalSourceWorkflowDefinition(
                name="apply_state",
                type=WorkflowType.INTERNAL,
                module="styrmin_backend.agent.tasks.orchestration",
                function="apply_state",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.RUN_JOB,
            workflow=LocalSourceWorkflowDefinition(
                name="run_job",
                type=WorkflowType.USER,
                module="styrmin_backend.agent.tasks.orchestration",
                function="run_job",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.CREATE_HELM_RELEASE,
            workflow=LocalSourceWorkflowDefinition(
                name="create_helm_release",
                type=WorkflowType.USER,
                module="styrmin_backend.agent.tasks.application",
                function="create_helm_release",
                set_directory="/source/backend/",
                # repository=config.SETTINGS.agent_code.repository,
                # branch=config.SETTINGS.agent_code.branch,
                # token=config.SETTINGS.agent_code.token,
                # namespace="core",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.UPDATE_HELM_RELEASE,
            workflow=LocalSourceWorkflowDefinition(
                name="update_helm_release",
                type=WorkflowType.USER,
                module="styrmin_backend.agent.tasks.application",
                function="update_helm_release",
                set_directory="/source/backend/",
                # repository=config.SETTINGS.agent_code.repository,
                # branch=config.SETTINGS.agent_code.branch,
                # token=config.SETTINGS.agent_code.token,
                # namespace="core",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.CREATE_INSTANCE,
            workflow=LocalSourceWorkflowDefinition(
                name="create_instance_crd",
                type=WorkflowType.USER,
                module="styrmin_backend.agent.tasks.orchestration",
                function="create_instance_crd",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.UPDATE_INSTANCE,
            workflow=LocalSourceWorkflowDefinition(
                name="update_instance_crd",
                type=WorkflowType.USER,
                module="styrmin_backend.agent.tasks.orchestration",
                function="update_instance_crd",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.UPGRADE_INSTANCE,
            workflow=LocalSourceWorkflowDefinition(
                name="upgrade_instance_crd",
                type=WorkflowType.USER,
                module="styrmin_backend.agent.tasks.orchestration",
                function="upgrade_instance_crd",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.EXECUTE_BACKUP,
            workflow=LocalSourceWorkflowDefinition(
                name="execute_backup",
                type=WorkflowType.INTERNAL,
                module="styrmin_backend.workflows.templates.backup",
                function="execute_backup_workflow",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.EXECUTE_RESTORE,
            workflow=LocalSourceWorkflowDefinition(
                name="execute_restore",
                type=WorkflowType.INTERNAL,
                module="styrmin_backend.workflows.templates.backup",
                function="execute_restore_workflow",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.EXECUTE_ENVIRONMENT_CLONE,
            workflow=LocalSourceWorkflowDefinition(
                name="execute_environment_clone",
                type=WorkflowType.INTERNAL,
                module="styrmin_backend.workflows.templates.clone",
                function="execute_environment_clone_workflow",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.EXECUTE_VELERO_BACKUP,
            workflow=LocalSourceWorkflowDefinition(
                name="execute_velero_backup",
                type=WorkflowType.USER,
                module="styrmin_backend.workflows.templates.backup",
                function="execute_velero_backup_flow",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.EXECUTE_VELERO_RESTORE,
            workflow=LocalSourceWorkflowDefinition(
                name="execute_velero_restore",
                type=WorkflowType.USER,
                module="styrmin_backend.workflows.templates.backup",
                function="execute_velero_restore_flow",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.APPLY_UTILITY_RESOURCES,
            workflow=LocalSourceWorkflowDefinition(
                name="apply_utility_resources",
                type=WorkflowType.USER,
                module="styrmin_backend.agent.tasks.application",
                function="apply_utility_resources",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.VALIDATE_CONNECTIVITY,
            workflow=LocalSourceWorkflowDefinition(
                name="validate_kubernetes_connectivity",
                type=WorkflowType.USER,
                module="styrmin_backend.workflows.connectivity",
                function="validate_kubernetes_connectivity",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.SYNC_BSL_CREATE,
            workflow=LocalSourceWorkflowDefinition(
                name="sync_bsl_create",
                type=WorkflowType.USER,
                module="styrmin_backend.workflows.templates.bsl_sync",
                function="sync_bsl_create_flow",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.SYNC_BSL_DELETE,
            workflow=LocalSourceWorkflowDefinition(
                name="sync_bsl_delete",
                type=WorkflowType.USER,
                module="styrmin_backend.workflows.templates.bsl_sync",
                function="sync_bsl_delete_flow",
                set_directory="/source/backend/",
            ),
        )

        self.add_workflow_definition(
            action=PrefectAction.SYNC_BSL_UPDATE_CREDENTIALS,
            workflow=LocalSourceWorkflowDefinition(
                name="sync_bsl_update_credentials",
                type=WorkflowType.USER,
                module="styrmin_backend.workflows.templates.bsl_sync",
                function="sync_bsl_update_credentials_flow",
                set_directory="/source/backend/",
            ),
        )

        # Daily sweep of expired session rows. See ADR-016.
        self.add_workflow_definition(
            action=PrefectAction.CLEANUP_EXPIRED_SESSIONS,
            workflow=LocalSourceWorkflowDefinition(
                name="cleanup_expired_sessions",
                type=WorkflowType.INTERNAL,
                module="styrmin_backend.workflows.templates.session_cleanup",
                function="cleanup_expired_sessions_flow",
                set_directory="/source/backend/",
                cron="17 3 * * *",
            ),
        )
