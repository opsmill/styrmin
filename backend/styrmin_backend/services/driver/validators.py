import ast
from abc import abstractmethod
from typing import Any

import jinja2

from styrmin_backend.services.driver.exceptions import (
    ValidationError,
)
from styrmin_backend.services.driver.models.resources.actions import (
    ActionDefinition,
    ActionsSpec,
)
from styrmin_backend.services.driver.models.resources.backup import (
    BackupKind,
    ComponentBackupConfig,
)
from styrmin_backend.services.driver.models.structure.resource import Role


class Validator:
    """The abstract validator class."""

    @abstractmethod
    def validate(self, data: Any) -> None:
        """Validate the object.

        Raises:
            ValidationError: If the object is invalid.
        """
        raise NotImplementedError


class JinjaTemplateValidator(Validator):
    """The Jinja template validator class.

    A validator that validates Jinja templates.
    """

    def validate(self, data: str) -> None:
        """Validate the Jinja template.

        Args:
            data (str): The Jinja template.

        Raises:
            ValidationError: If the template is invalid
        """
        from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
            get_jinja_environment,
        )

        try:
            env = get_jinja_environment()
            env.from_string(data)
        except jinja2.exceptions.TemplateSyntaxError as err:
            raise ValidationError(str(err)) from err


class UserActionsValidator(Validator):
    def __init__(self, entrypoints: list[ActionDefinition]) -> None:
        self.entrypoints = entrypoints

    def validate(self, data: Any) -> None:
        parsed_ast = ast.parse(data)

        # Very basic validation: ensure that the code contains the expected entrypoints
        found_entrypoints = set()
        for node in parsed_ast.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found_entrypoints.add(node.name)

        # Ensure that the code contains the expected entrypoints with the correct signature
        for entrypoint in self.entrypoints:
            code_func_name = entrypoint.location.split("::")[-1]
            # Find the function in the code at the root of the module
            if code_func_name not in found_entrypoints:
                raise ValidationError(
                    f"Missing entrypoint for action {entrypoint.name}: {code_func_name}"
                )


class BackupConfigValidator(Validator):
    """Validates ComponentBackupConfig entries during driver loading.

    Cross-references backup configuration against the driver spec components (volume names)
    and the actions spec (action hooks) to ensure consistency.

    Attributes:
        component_volumes: Mapping of component name to available volume names.
        action_hooks: Set of hook names defined in the actions spec.
    """

    def __init__(
        self,
        component_volumes: dict[str, list[str]] | None = None,
        action_hooks: set[str] | None = None,
    ) -> None:
        self.component_volumes = component_volumes or {}
        self.action_hooks = action_hooks or set()

    def validate(self, data: Any) -> None:
        """Validate a mapping of component names to ComponentBackupConfig.

        Args:
            data: A dict mapping component names to ComponentBackupConfig instances.

        Raises:
            ValidationError: If any backup configuration is invalid.
        """
        if not isinstance(data, dict):
            raise ValidationError(
                "Backup config data must be a dict mapping component names to configs"
            )

        for component_name, config in data.items():
            if not isinstance(config, ComponentBackupConfig):
                raise ValidationError(
                    f"Backup config for component '{component_name}' must be a ComponentBackupConfig instance"
                )
            self._validate_component(component_name, config)

    def _validate_component(
        self, component_name: str, config: ComponentBackupConfig
    ) -> None:
        """Validate a single component's backup configuration.

        Args:
            component_name: The name of the component.
            config: The backup configuration for the component.

        Raises:
            ValidationError: If the backup configuration is invalid.
        """
        if not config.enabled:
            return

        if config.kind is None:
            raise ValidationError(
                f"Component '{component_name}': kind is required when backup is enabled"
            )

        match config.kind:
            case BackupKind.DISK:
                self._validate_disk(component_name, config)
            case BackupKind.ACTION:
                self._validate_action(component_name)
            case (
                BackupKind.MARIADB
                | BackupKind.MONGODB
                | BackupKind.POSTGRES
                | BackupKind.NEO4J
            ):
                # Database kinds have no extra cross-referencing requirements
                pass

    def _validate_disk(
        self, component_name: str, config: ComponentBackupConfig
    ) -> None:
        """Validate disk backup configuration volume references.

        For disk kind, at least one volume must be specified and all referenced volumes
        must exist in the component's known volumes (when volume information is available).

        Args:
            component_name: The name of the component.
            config: The backup configuration for the component.

        Raises:
            ValidationError: If volume references are missing or invalid.
        """
        referenced_volumes: list[str] = []
        if config.volumes:
            referenced_volumes = list(config.volumes)
        elif config.volume:
            referenced_volumes = [config.volume]

        if not referenced_volumes:
            raise ValidationError(
                f"Component '{component_name}': disk backup requires at least one volume "
                "(set 'volume' or 'volumes')"
            )

        known_volumes = self.component_volumes.get(component_name)
        if known_volumes is not None:
            for vol in referenced_volumes:
                if vol not in known_volumes:
                    raise ValidationError(
                        f"Component '{component_name}': volume '{vol}' is not defined. "
                        f"Available volumes: {known_volumes}"
                    )

    def _validate_action(self, component_name: str) -> None:
        """Validate action backup configuration hooks.

        For action kind, the actions spec must define hooks named 'backup' and 'restore'.

        Args:
            component_name: The name of the component.

        Raises:
            ValidationError: If required action hooks are missing.
        """
        missing_hooks = {"backup", "restore"} - self.action_hooks
        if missing_hooks:
            raise ValidationError(
                f"Component '{component_name}': action backup requires action hooks "
                f"{sorted(missing_hooks)} to be defined in the actions spec"
            )


def validate_driver_backup_configs(
    backup_configs: dict[str, ComponentBackupConfig],
    component_volumes: dict[str, list[str]] | None = None,
    actions_spec: ActionsSpec | None = None,
) -> None:
    """Validate backup configurations against the driver definition.

    This is the entry point for backup config validation during driver processing.

    Args:
        backup_configs: Mapping of component name to ComponentBackupConfig.
        component_volumes: Mapping of component name to available volume names.
        actions_spec: The actions spec, used to extract hook names for action backups.

    Raises:
        ValidationError: If any backup configuration is invalid.
    """
    action_hooks: set[str] = set()
    if actions_spec is not None:
        action_hooks = {action.name for action in actions_spec.spec.actions}

    validator = BackupConfigValidator(
        component_volumes=component_volumes,
        action_hooks=action_hooks,
    )
    validator.validate(backup_configs)


def build_user_actions_validator(actions_spec: ActionsSpec) -> UserActionsValidator:
    """Build a user actions validator.

    Args:
        entrypoints (ActionDefinition): The entrypoints.

    Returns:
        UserActionsValidator: The user actions validator.
    """
    entrypoints = actions_spec.spec.actions
    return UserActionsValidator(entrypoints=entrypoints)


def get_validator(role: Role) -> Validator | None:
    """Get the validator based on the role.

    Args:
        role (Role): The role.

    Returns:
        Validator: The validator.
    """
    match role:
        case Role.DRIVER_SPEC | Role.ACTIONS_SPEC:
            # For this role, the validation is indissociable from the deserialization
            return None
        case Role.VALUES_TEMPLATE:
            return JinjaTemplateValidator()
        case _:
            raise ValueError(f"Unsupported role: {role!r}")
