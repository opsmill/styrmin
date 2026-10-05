from dataclasses import dataclass, field

from styrmin_backend.services.driver.models.resources.actions import ActionDefinition
from styrmin_backend.services.driver.models.structure.source import GitSource
from styrmin_backend.workflows.constants import WorkflowType
from styrmin_backend.workflows.models import (
    DeploymentInfo,
    GitSourceWorkflowDefinition,
)


@dataclass
class PrefectDeploymentsCatalogue:
    actions: dict[str, DeploymentInfo] = field(default_factory=dict)


class ActionsWorkflowBuilder:
    USER_NAMESPACE = "user"

    def __init__(self, source: GitSource, commit_sha: str | None = None):
        self.source: GitSource = source
        # ``ApplicationDriverVersion.source_commit_sha``: every action pins to it.
        self.commit_sha: str | None = commit_sha

    def build_user_action_workflow_definition(
        self, action: ActionDefinition
    ) -> GitSourceWorkflowDefinition:
        workflow_name = f"User Action: {action.name}"
        module, function = action.location.split("::")
        workflow_definition = GitSourceWorkflowDefinition(
            name=workflow_name,
            module=module,
            function=function,
            repository=self.source.repository,
            branch=self.source.branch,
            commit_sha=self.commit_sha,
            namespace=self.USER_NAMESPACE,
            token=self.source.token,
            type=WorkflowType.USER,
            image=action.image,
        )
        return workflow_definition
