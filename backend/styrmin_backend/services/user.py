from dataclasses import dataclass, field

from styrmin_backend import config
from styrmin_backend.services.driver.exceptions import DriverLoadingError
from styrmin_backend.services.driver.models.resources.actions import ActionDefinition
from styrmin_backend.services.driver.models.structure.source import (
    GitSource,
    LocalSource,
)
from styrmin_backend.workflows.constants import WorkflowType
from styrmin_backend.workflows.models import (
    DeploymentInfo,
    GitSourceWorkflowDefinition,
    LocalDriverActionWorkflowDefinition,
)


@dataclass
class PrefectDeploymentsCatalogue:
    actions: dict[str, DeploymentInfo] = field(default_factory=dict)


class ActionsWorkflowBuilder:
    USER_NAMESPACE = "user"

    def __init__(
        self,
        source: GitSource | LocalSource,
        commit_sha: str | None = None,
        content_hash: str | None = None,
    ):
        self.source: GitSource | LocalSource = source
        # ``ApplicationDriverVersion.source_commit_sha``: every action pins to it.
        self.commit_sha: str | None = commit_sha
        # ``ApplicationDriverVersion.content_hash``: the check before every
        # action of a local driver version compares the files with it.
        self.content_hash: str | None = content_hash
        if isinstance(source, LocalSource) and not content_hash:
            raise DriverLoadingError(
                f"The driver loaded from {source.path} has no provenance fingerprint, "
                "so its actions cannot be registered. Load the driver again."
            )

    def build_user_action_workflow_definition(
        self, action: ActionDefinition
    ) -> GitSourceWorkflowDefinition | LocalDriverActionWorkflowDefinition:
        workflow_name = f"User Action: {action.name}"
        module, function = action.location.split("::")
        if isinstance(self.source, LocalSource):
            # Spec 029: the action runs from the path of the driver version,
            # after a check of its files (research R-001).
            driver_settings = config.SETTINGS.driver
            return LocalDriverActionWorkflowDefinition(
                name=workflow_name,
                module=module,
                function=function,
                type=WorkflowType.USER,
                image=action.image,
                directory=self.source.path,
                content_hash=self.content_hash,
                spec_file=driver_settings.spec_file,
                values_template=driver_settings.values_template,
                actions_file=driver_settings.actions_code_file,
            )
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
            # Spec 028: the action runs from its driver directory, if any.
            set_directory=self.source.driver_directory,
        )
        return workflow_definition
