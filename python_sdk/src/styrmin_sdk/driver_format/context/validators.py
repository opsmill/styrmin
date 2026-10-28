from pydantic import ValidationError

from styrmin_sdk.driver_format.context.exceptions import (
    InvalidClusterContextError,
    InvalidDeploymentContextError,
    InvalidEnvironmentContextError,
)
from styrmin_sdk.driver_format.context.models.config import (
    BaseConfigSection,
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
)

# Pydantic decorates a validator's own message with the kind of failure that
# produced it (``ValueError`` → "Value error, …", ``assert`` → "Assertion
# failed, …"). That tag describes our implementation, not the caller's mistake,
# so it is stripped before the message crosses the API boundary.
_PYDANTIC_MESSAGE_PREFIXES = ("Value error, ", "Assertion failed, ")

_FALLBACK_MESSAGE = "configuration validation failed"


def format_config_validation_error(error: ValidationError) -> str:
    """Render a config ``ValidationError`` as ``field: reason`` pairs.

    The whole value of a config rejection to an API client is *which field* is
    wrong and *how to fix it* — 016 / FR-004 makes that part of the requirement
    for ``backup_ttl``, whose message carries the syntax hint. ``str(error)``
    delivers that, but wrapped in Pydantic's full repr: the internal model class
    name, a ``type=`` tag, an ``input_value=`` echo, a ``pydantic.dev`` URL, and
    newlines that no other typed error in this project emits.

    This keeps the two load-bearing halves — the field location and the
    validator's message — and drops the rest. Only ``loc`` and ``msg`` are read,
    which is also what keeps a nested failure readable: a ``model_validator`` on
    a submodel reports the entire submodel dict as ``input``, so any formatting
    that touched ``input`` would dump a large blob for exactly the configs that
    are hardest to debug.

    Args:
        error: The Pydantic error raised while parsing a config section.

    Returns:
        A single-line message. One entry per validation failure, joined with
        ``"; "``; each entry is the dotted field path and the validator's
        message, or just the message for a failure on the model as a whole.
    """
    entries: list[str] = []
    for detail in error.errors():
        message = detail["msg"]
        for prefix in _PYDANTIC_MESSAGE_PREFIXES:
            if message.startswith(prefix):
                message = message[len(prefix) :]
                break
        # A validator message may itself span lines; collapse so the result is
        # one line however the underlying rule chose to format itself.
        message = " ".join(message.split())
        location = ".".join(str(part) for part in detail["loc"])
        entries.append(f"{location}: {message}" if location else message)
    return "; ".join(entries) or _FALLBACK_MESSAGE


def _required_node_affinity_term_errors(config: BaseConfigSection) -> str | None:
    """Name each required node affinity term that has no expression.

    Such a term renders as no node selector term or an empty one, so the pods run on
    any node or on none (#496). Only a save rejects it: stored configs still load.
    """
    node_affinity = config.scheduling.node_affinity if config.scheduling else None
    if node_affinity is None:
        return None
    entries = [
        f"scheduling.node_affinity.required.{index}: a required node affinity term "
        "must set at least one entry in label_selector.match_expressions or "
        "label_selector.match_labels"
        for index, term in enumerate(node_affinity.required)
        if term.label_selector is None
        or not (term.label_selector.match_expressions or term.label_selector.match_labels)
    ]
    return "; ".join(entries) or None


def validate_cluster_config(context: dict) -> None:
    """Validate the cluster context.

    Raises:
        InvalidClusterContextError: If the cluster context is invalid.
    """

    try:
        ClusterConfig(**context)
    except ValidationError as e:
        # Carry the field name and the validator's own message forward:
        # field-level rules (e.g. ``backup_ttl``, 016 / FR-004) state which
        # field failed and how to fix it, and that hint is the whole value of
        # the error to the caller.
        raise InvalidClusterContextError(format_config_validation_error(e)) from e


def validate_environment_config(context: dict) -> None:
    """Validate the environment context.

    Raises:
        InvalidEnvironmentContextError: If the environment context is invalid.
    """

    try:
        config = EnvironmentConfig(**context)
    except ValidationError as e:
        raise InvalidEnvironmentContextError(format_config_validation_error(e)) from e
    if message := _required_node_affinity_term_errors(config):
        raise InvalidEnvironmentContextError(message)


def validate_deployment_config(context: dict) -> None:
    """Validate the instance context.

    Raises:
        InvalidInstanceContextError: If the instance context is invalid.
    """

    try:
        config = DeploymentConfig(**context)
    except ValidationError as e:
        raise InvalidDeploymentContextError(format_config_validation_error(e)) from e
    if message := _required_node_affinity_term_errors(config):
        raise InvalidDeploymentContextError(message)
