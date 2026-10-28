"""The example context: the context that the server would build for a new deployment of a driver.

``styrmin-driver`` renders a driver's values template with it when the author gives no
context file, and merges an author's context file into it. It is the context of a new
deployment with the default parameters, on a cluster and an environment with no
configuration, with fixed identifiers (specs/032-styrmin-driver-cli, research R-006 to R-008).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from packaging.specifiers import InvalidSpecifier, Specifier
from pydantic import ValidationError

from styrmin_sdk.driver_format.context.exceptions import ContextError
from styrmin_sdk.driver_format.context.models.contexts import GlobalContext, UtilityContext, UtilityKind
from styrmin_sdk.driver_format.context.models.input import ContextInput
from styrmin_sdk.driver_format.context.naming import (
    get_chart_name_from_chart_url,
    get_chart_repository_from_chart_url,
    get_kubernetes_reference,
)
from styrmin_sdk.driver_format.context.parameters import validate_parameter_values
from styrmin_sdk.driver_format.context.resolvers import resolve_global_context
from styrmin_sdk.driver_format.context.service_entries import build_service_entries
from styrmin_sdk.driver_format.errors import ServiceError
from styrmin_sdk.driver_format.models.resources.driver import DriverSpec
from styrmin_sdk.driver_format.models.resources.parameters import DriverParameterDefinition, DriverParameterKind

# Fixed identifiers, so that two runs give the same context and the same rendered values.
EXAMPLE_DEPLOYMENT_ID = UUID("00000000-0000-4000-8000-000000000001")
EXAMPLE_ENVIRONMENT_ID = UUID("00000000-0000-4000-8000-000000000002")
EXAMPLE_CHART_ID = UUID("00000000-0000-4000-8000-000000000003")
EXAMPLE_REPOSITORY_ID = UUID("00000000-0000-4000-8000-000000000004")
EXAMPLE_INSTANCE_ID = UUID("00000000-0000-4000-8000-000000000005")
EXAMPLE_ENVIRONMENT_NAME = "example"
FALLBACK_APPLICATION_VERSION = "0.0.0"


@dataclass(frozen=True)
class ExampleWarning:
    """A value that the example context had to make up, with the YAML path of the declaration."""

    path: tuple[str | int, ...]
    message: str


@dataclass
class ExampleContext:
    """The example context of a driver, and the warnings about the values it made up."""

    context: GlobalContext
    warnings: list[ExampleWarning] = field(default_factory=list)


@dataclass(frozen=True)
class _ServiceRow:
    driver_service_name: str
    resolved_name: str
    port: int
    kind: str
    component: str
    deployment_id: UUID


class ContextFileError(Exception):
    """A context file that cannot be merged into the example context, or whose result is invalid.

    ``problems`` holds one ``(key path, message)`` pair per problem.
    """

    def __init__(self, problems: list[tuple[str, str]]) -> None:
        self.problems = problems
        super().__init__("; ".join(f"{path}: {message}" if path else message for path, message in problems))


def placeholder_value(definition: DriverParameterDefinition) -> str | int | bool:
    """The placeholder that the example context gives a parameter without a default (R-006)."""
    match definition.kind:
        case DriverParameterKind.INTEGER:
            return 0
        case DriverParameterKind.BOOLEAN:
            return False
        case DriverParameterKind.ENUM:
            return (definition.values or [""])[0]
        case _:
            return f"example-{definition.name}"


def example_application_version(supported_versions: str) -> str:
    """The version of the first ``>=``, ``==`` or ``~=`` clause of a specifier, or ``0.0.0``.

    The clauses are read in the order they are written. ``SpecifierSet`` keeps them in a
    set, whose order changes from one Python process to the next.
    """
    for clause in supported_versions.split(","):
        try:
            specifier = Specifier(clause.strip())
        except InvalidSpecifier:
            continue
        if specifier.operator in {">=", "==", "~="} and "*" not in specifier.version:
            return specifier.version
    return FALLBACK_APPLICATION_VERSION


def build_example_context(driver_spec: DriverSpec, values_template: str) -> ExampleContext:
    """Build the context that the server would build for a new deployment of the driver.

    The parameters are the defaults, and a placeholder for each parameter without one. The
    cluster, the environment and the deployment have no configuration. The identifiers are
    the ``EXAMPLE_*`` constants.
    """
    spec = driver_spec.spec
    warnings: list[ExampleWarning] = []

    definitions = spec.parameters or []
    values: dict[str, Any] = {}
    for index, definition in enumerate(definitions):
        if definition.default is None:
            values[definition.name] = placeholder_value(definition)
            warnings.append(
                ExampleWarning(
                    path=("spec", "parameters", index, "name"),
                    message=(
                        f"parameter '{definition.name}' has no default; the example context uses "
                        f"the placeholder {values[definition.name]!r}"
                    ),
                )
            )
    parameters = validate_parameter_values(definitions=definitions, values=values)

    version = spec.default_version
    if version is None:
        version = example_application_version(spec.supported_versions)
        warnings.append(
            ExampleWarning(
                path=("spec", "supported_versions"),
                message=(
                    f"no default_version; the example context uses application version '{version}'; "
                    "set app.version in a context file to change it"
                ),
            )
        )

    namespace = get_kubernetes_reference(EXAMPLE_DEPLOYMENT_ID)
    components = spec.components.model_dump() if spec.components else {}
    context_input = ContextInput.model_validate(
        {
            "config": {"cluster": {}, "environment": {}, "deployment": {}},
            "instance": {
                "deployment_id": EXAMPLE_DEPLOYMENT_ID,
                "namespace": namespace,
                "release_reference": namespace,
            },
            "application": {
                "name": driver_spec.metadata.name,
                "version": version,
                "chart": {
                    "id": EXAMPLE_CHART_ID,
                    "name": get_chart_name_from_chart_url(spec.helm.main.location),
                    "version": spec.helm.main.version,
                    "values_template": values_template,
                },
                "repository": {
                    "id": EXAMPLE_REPOSITORY_ID,
                    "url": get_chart_repository_from_chart_url(spec.helm.main.location),
                },
            },
            "components": [{"name": name, "enabled": True, "config": config} for name, config in components.items()],
            "utilities": [{"kind": UtilityKind.INGRESS.value}],
            "environment_name": EXAMPLE_ENVIRONMENT_NAME,
            "labels": {"environment_id": EXAMPLE_ENVIRONMENT_ID, "deployment_id": EXAMPLE_DEPLOYMENT_ID},
            "parameters": parameters,
            "driver_version": f"{driver_spec.metadata.name} {spec.version} (example)",
        }
    )
    context = resolve_global_context(context_input=context_input)
    context.instance.id = EXAMPLE_INSTANCE_ID
    context.cluster.capabilities = {}
    context.environment.capabilities = {}

    rows = [
        _ServiceRow(
            driver_service_name=service.name,
            resolved_name=service.name,
            port=service.port,
            kind=service.kind.value,
            component=service.component,
            deployment_id=EXAMPLE_DEPLOYMENT_ID,
        )
        for service in spec.services or []
    ]
    context.services, context.deployed_services, has_own_services = build_service_entries(
        rows,
        app_name=driver_spec.metadata.name,
        deployment_id=EXAMPLE_DEPLOYMENT_ID,
        environment_name=EXAMPLE_ENVIRONMENT_NAME,
        fqdn_suffix=context.instance.config.fqdn_suffix,
    )
    if has_own_services:
        context.utilities.append(UtilityContext(kind=UtilityKind.SERVICE_DISCOVERY))
    return ExampleContext(context=context, warnings=warnings)


def _merge(base: Any, overlay: Any) -> Any:  # noqa: ANN401
    """Merge ``overlay`` into ``base``: mappings merge key by key, any other value replaces."""
    if isinstance(base, Mapping) and isinstance(overlay, Mapping):
        merged = dict(base)
        for key, value in overlay.items():
            merged[key] = _merge(base.get(key), value) if key in base else value
        return merged
    return overlay


def _key_path(loc: tuple[int | str, ...]) -> str:
    path = ""
    for part in loc:
        path += f"[{part}]" if isinstance(part, int) else f".{part}" if path else str(part)
    return path


def merge_context_file(example: GlobalContext, data: object, values_template: str) -> tuple[GlobalContext, bool]:
    """Merge the content of an author's context file into the example context (R-008).

    Returns the merged context, and whether the file set a different values template, which
    the merge replaces with the directory's template.

    Raises:
        ContextFileError: If ``data`` is not a mapping, or the merged context does not match
            the context model.
    """
    if not isinstance(data, Mapping):
        raise ContextFileError([("", f"the top level must be a mapping, not {type(data).__name__}")])
    merged = _merge(example.model_dump(mode="json", exclude_none=True), data)
    # The file may give any shape at any level; the model check below reports a wrong one.
    app = merged.get("app")
    helm = app.get("helm") if isinstance(app, Mapping) else None
    chart = helm.get("chart") if isinstance(helm, Mapping) else None
    template_replaced = False
    if isinstance(chart, dict):
        template_replaced = chart.get("values_template", values_template) != values_template
        chart["values_template"] = values_template
    try:
        return GlobalContext.model_validate(merged), template_replaced
    except ValidationError as err:
        raise ContextFileError(
            [(_key_path(error["loc"]), error["msg"]) for error in err.errors(include_url=False)]
        ) from err
    except (ServiceError, ContextError, ValueError, TypeError) as err:
        # A validator of the context model that raises its own error, such as an invalid
        # environment variable name, instead of a Pydantic error.
        raise ContextFileError([("", str(err))]) from err
