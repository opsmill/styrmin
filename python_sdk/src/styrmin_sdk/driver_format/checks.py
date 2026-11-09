import ast
from abc import abstractmethod
from typing import Any, cast, get_args

import jinja2
from jinja2 import nodes

from styrmin_sdk.driver_format.context.validation.env_vars.exceptions import (
    DriverEnvVarDocComponentMismatchError,
)
from styrmin_sdk.driver_format.errors import (
    RetiredTemplateFilter,
    RetiredTemplateFilterError,
    ValidationError,
    retired_filter_load_message,
)
from styrmin_sdk.driver_format.models.resources.actions import (
    ActionDefinition,
)
from styrmin_sdk.driver_format.models.resources.backup import (
    BackupKind,
    ComponentBackupConfig,
)
from styrmin_sdk.driver_format.models.resources.driver import Specification
from styrmin_sdk.driver_format.models.resources.env_vars import (
    DriverEnvVarLevel,
)
from styrmin_sdk.driver_format.models.structure.resource import Role

_RETIRED_FILTERS: frozenset[str] = frozenset(get_args(RetiredTemplateFilter))


def find_retired_filters(template_ast: nodes.Template) -> list[tuple[RetiredTemplateFilter, int]]:
    """Every call of a retired template filter in a parsed template, with its line, in the order Jinja walks the tree."""
    found: list[tuple[RetiredTemplateFilter, int]] = []
    for node in template_ast.find_all(nodes.Filter):
        if node.name in _RETIRED_FILTERS:
            found.append((cast("RetiredTemplateFilter", node.name), node.lineno))
    return found


def entrypoint_function_name(action: ActionDefinition) -> str:
    """The function name of an action's ``location``, the part after ``::``."""
    return action.location.split("::")[-1]


def find_missing_entrypoints(code: str, actions: list[ActionDefinition]) -> list[ActionDefinition]:
    """Every action whose function is not defined at the top level of ``code``, in declaration order.

    Raises:
        SyntaxError: If ``code`` is not valid Python.
    """
    parsed_ast = ast.parse(code)

    # Very basic validation: ensure that the code contains the expected entrypoints
    found_entrypoints = set()
    for node in parsed_ast.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found_entrypoints.add(node.name)

    # Find the function of each action at the root of the module
    return [action for action in actions if entrypoint_function_name(action) not in found_entrypoints]


def missing_entrypoint_message(action: ActionDefinition) -> str:
    """The load's message for an action whose function ``actions.py`` does not define."""
    return f"Missing entrypoint for action {action.name}: {entrypoint_function_name(action)}"


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
            RetiredTemplateFilterError: If the template calls a retired filter, which
                would otherwise fail only when the operator renders it.
        """
        from styrmin_sdk.driver_format.rendering import (
            get_jinja_environment,
        )

        try:
            env = get_jinja_environment()
            template_ast = env.parse(data)
            env.from_string(template_ast)
        except jinja2.exceptions.TemplateSyntaxError as err:
            raise ValidationError(str(err)) from err

        for name, lineno in find_retired_filters(template_ast):
            raise RetiredTemplateFilterError(retired_filter_load_message(name, lineno), filter_name=name)


class UserActionsValidator(Validator):
    def __init__(self, entrypoints: list[ActionDefinition]) -> None:
        self.entrypoints = entrypoints

    def validate(self, data: Any) -> None:
        for entrypoint in find_missing_entrypoints(data, self.entrypoints):
            raise ValidationError(missing_entrypoint_message(entrypoint))


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
            raise ValidationError("Backup config data must be a dict mapping component names to configs")

        for component_name, config in data.items():
            if not isinstance(config, ComponentBackupConfig):
                raise ValidationError(
                    f"Backup config for component '{component_name}' must be a ComponentBackupConfig instance"
                )
            self._validate_component(component_name, config)

    def _validate_component(self, component_name: str, config: ComponentBackupConfig) -> None:
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
            raise ValidationError(f"Component '{component_name}': kind is required when backup is enabled")

        match config.kind:
            case BackupKind.DISK:
                self._validate_disk(component_name, config)
            case BackupKind.ACTION:
                self._validate_action(component_name)
            case BackupKind.MARIADB | BackupKind.MONGODB | BackupKind.POSTGRES | BackupKind.NEO4J:
                # Database kinds have no extra cross-referencing requirements
                pass

    def _validate_disk(self, component_name: str, config: ComponentBackupConfig) -> None:
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
                f"Component '{component_name}': disk backup requires at least one volume (set 'volume' or 'volumes')"
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
    actions: list[ActionDefinition] | None = None,
) -> None:
    """Validate backup configurations against the driver definition.

    This is the entry point for backup config validation during driver processing.

    Args:
        backup_configs: Mapping of component name to ComponentBackupConfig.
        component_volumes: Mapping of component name to available volume names.
        actions: List of action definitions, used to extract hook names for action backups.

    Raises:
        ValidationError: If any backup configuration is invalid.
    """
    action_hooks: set[str] = set()
    if actions is not None:
        action_hooks = {action.name for action in actions}

    validator = BackupConfigValidator(
        component_volumes=component_volumes,
        action_hooks=action_hooks,
    )
    validator.validate(backup_configs)


def validate_driver_backup_configs_for_spec(specification: Specification) -> None:
    """Validate the ``backup`` block of every component in a driver spec.

    Run at driver-load time (alongside the other ``validate_driver_*`` checks)
    so a misconfigured backup fails loudly at registration instead of silently
    no-opping at backup time — e.g. ``kind: disk`` with no ``volume``/``volumes``
    produces no Velero ``backup-volumes`` annotation and captures nothing.

    Volume *existence* is not cross-checked here because the chart's rendered
    pod-template volume names aren't known until deploy time; the "disk backup
    requires at least one volume" rule (and the action-hook rule) still fire,
    which is what guards against the silent no-op.

    Raises:
        ValidationError: If any component's backup configuration is invalid.
    """
    if specification.components is None:
        return

    backup_configs: dict[str, ComponentBackupConfig] = {}
    for name, component in specification.components.root.items():
        backup_raw = (component.__pydantic_extra__ or {}).get("backup")
        if backup_raw is None:
            continue
        try:
            backup_configs[name] = ComponentBackupConfig.model_validate(backup_raw)
        except ValueError as exc:
            raise ValidationError(f"Component '{name}': invalid backup configuration: {exc}") from exc

    if not backup_configs:
        return

    validate_driver_backup_configs(
        backup_configs=backup_configs,
        actions=specification.actions,
    )


def validate_driver_env_var_docs(specification: Specification) -> None:
    """Cross-validate ``spec.env_vars`` doc entries against the driver's components.

    FR-013 / FR-014: every component referenced by an ``env_vars`` doc whose
    ``level=component`` MUST exist in ``Specification.components.root``. The
    Pydantic field/model validators on :class:`DriverEnvVarDoc` already
    enforce per-entry shape (name regex, level/components consistency, name
    uniqueness within the list); this function runs the **cross-field**
    rule that needs the parent ``Specification``.

    Raises:
        DriverEnvVarDocComponentMismatchError: when a component reference
            does not resolve to a declared component. The error metadata
            carries the offending env var name, the bad component name,
            and the driver's known component names so the failure message
            is actionable.
    """
    if not specification.env_vars:
        return

    declared_components: set[str] = set()
    if specification.components is not None:
        declared_components = set(specification.components.root.keys())

    known_sorted = sorted(declared_components)
    for doc in specification.env_vars:
        if doc.level is not DriverEnvVarLevel.COMPONENT:
            continue
        for component_name in doc.components:
            if component_name not in declared_components:
                raise DriverEnvVarDocComponentMismatchError(
                    name=doc.name,
                    component_name=component_name,
                    known_components=known_sorted,
                )


def build_user_actions_validator(
    actions: list[ActionDefinition],
) -> UserActionsValidator:
    """Build a user actions validator.

    Args:
        actions: The action definitions with entrypoints.

    Returns:
        UserActionsValidator: The user actions validator.
    """
    return UserActionsValidator(entrypoints=actions)


def get_validator(role: Role) -> Validator | None:
    """Get the validator based on the role.

    Args:
        role (Role): The role.

    Returns:
        Validator: The validator.
    """
    match role:
        case Role.DRIVER_SPEC:
            # For this role, the validation is indissociable from the deserialization
            return None
        case Role.VALUES_TEMPLATE:
            return JinjaTemplateValidator()
        case _:
            raise ValueError(f"Unsupported role: {role!r}")
