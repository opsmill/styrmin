"""Run every check of a driver directory and collect every problem, with its file and line.

The server's load stops at the first problem. ``run_checks`` runs the same checks, with the
same messages, and keeps going, so that ``styrmin-driver check`` reports every problem in
one run (specs/032-styrmin-driver-cli, FR-001, FR-009, research R-005 and R-015).
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import jinja2
import yaml
from pydantic import ValidationError as PydanticValidationError
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from styrmin_sdk.driver_format.checks import (
    find_missing_entrypoints,
    find_retired_filters,
    missing_entrypoint_message,
    validate_driver_backup_configs_for_spec,
    validate_driver_env_var_docs,
)
from styrmin_sdk.driver_format.context.exceptions import ContextError
from styrmin_sdk.driver_format.context.models.contexts import GlobalContext
from styrmin_sdk.driver_format.context.validation.env_vars.exceptions import (
    DriverEnvVarDocComponentMismatchError,
    InvalidEnvVarNameError,
)
from styrmin_sdk.driver_format.errors import (
    DeserializationError,
    ParsingError,
    ServiceError,
    ValidationError,
    retired_filter_load_message,
)
from styrmin_sdk.driver_format.example_context import (
    ExampleContext,
    build_example_context,
    merge_context_file,
)
from styrmin_sdk.driver_format.models.resources.actions import ActionDefinition
from styrmin_sdk.driver_format.models.resources.driver import DriverSpec
from styrmin_sdk.driver_format.models.structure.directory import DriverFileNames
from styrmin_sdk.driver_format.reading.deserializers import DriverSpecDeserializer, validation_error_fields
from styrmin_sdk.driver_format.reading.parsers import YamlParser
from styrmin_sdk.driver_format.rendering import RenderResult, get_jinja_environment, render_values_checked

Severity = Literal["error", "warning"]

#: The checks of the values template and its render. An error of one of them does not
#: change the context, so the ``context`` command ignores them.
TEMPLATE_CHECKS = frozenset(
    {"template-file", "template-syntax", "retired-filter", "undefined-variable", "render", "values-yaml"}
)
YamlPath = tuple[str | int, ...]


@dataclass(frozen=True)
class Diagnostic:
    """One problem or warning, with the file and, when known, the line (data-model.md)."""

    severity: Severity
    file: str
    line: int | None
    message: str
    check: str

    def format(self) -> str:
        """``<file>:<line>: <severity>: <message>``, the format that editors and CI read."""
        where = f"{self.file}:{self.line}" if self.line is not None else self.file
        return f"{where}: {self.severity}: {self.message}"


@dataclass
class CheckReport:
    """The result of the checks on one driver directory (data-model.md)."""

    diagnostics: list[Diagnostic] = field(default_factory=list)
    spec: DriverSpec | None = None
    template: str = ""
    template_valid: bool = False
    example: ExampleContext | None = None
    context: GlobalContext | None = None
    rendered: RenderResult | None = None

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]


def node_line(root: Node | None, path: YamlPath) -> int | None:
    """The line of the deepest node of ``path`` in a composed YAML document (1-based).

    The line of a mapping entry is the line of its key. When the path leaves the document,
    for example at a key that is missing, the line is that of the last node found.
    """
    if root is None:
        return None
    node: Node = root
    line = node.start_mark.line + 1
    for part in path:
        if isinstance(node, MappingNode):
            entry = next(
                ((k, v) for k, v in node.value if isinstance(k, ScalarNode) and k.value == str(part)),
                None,
            )
            if entry is None:
                break
            line = entry[0].start_mark.line + 1
            node = entry[1]
        elif isinstance(node, SequenceNode) and isinstance(part, int) and 0 <= part < len(node.value):
            node = node.value[part]
            line = node.start_mark.line + 1
        else:
            break
    return line


def _sequence_index(root: Node | None, path: YamlPath, key: str, value: str) -> int | None:
    """The index of the entry of the sequence at ``path`` whose ``key`` is ``value``."""
    node = root
    for part in path:
        if not isinstance(node, MappingNode):
            return None
        node = next((v for k, v in node.value if isinstance(k, ScalarNode) and k.value == part), None)
    if not isinstance(node, SequenceNode):
        return None
    for index, item in enumerate(node.value):
        if isinstance(item, MappingNode) and any(
            isinstance(k, ScalarNode) and k.value == key and isinstance(v, ScalarNode) and v.value == value
            for k, v in item.value
        ):
            return index
    return None


class _Collector:
    def __init__(self, display_root: str, file_names: DriverFileNames) -> None:
        self.spec_file = str(Path(display_root) / file_names.spec_file)
        self.template_file = str(Path(display_root) / file_names.values_template)
        self.actions_file = str(Path(display_root) / file_names.actions_code)
        self.items: list[Diagnostic] = []

    def add(self, severity: Severity, file: str, line: int | None, message: str, check: str) -> None:
        self.items.append(Diagnostic(severity=severity, file=file, line=line, message=message, check=check))

    def sorted(self) -> list[Diagnostic]:
        rank = {self.spec_file: 0, self.template_file: 1, self.actions_file: 2}
        order = {id(d): i for i, d in enumerate(self.items)}
        return sorted(self.items, key=lambda d: (rank.get(d.file, 3), d.line or 0, order[id(d)]))


class _Unreadable:
    """A driver file that exists but cannot be read; its error is already collected."""


_UNREADABLE = _Unreadable()


def _read_driver_file(path: Path, file: str, out: _Collector, check: str) -> str | _Unreadable:
    """The text of a driver file. A file that cannot be read, or is not UTF-8, is an error.

    Raises:
        FileNotFoundError: If the file does not exist; each caller decides what that means.
    """
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise
    except OSError as err:
        out.add("error", file, None, f"The file cannot be read: {err.strerror or err}", check)
        return _UNREADABLE
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as err:
        line = data[: err.start].count(b"\n") + 1
        out.add("error", file, line, f"The file is not valid UTF-8: {err.reason} at byte {err.start}", check)
        return _UNREADABLE


def _parse_spec_file(path: Path, out: _Collector) -> tuple[object, Node | None] | None:
    """The parsed data and the composed YAML of ``driver.styrmin.yml``, or None after an error."""
    try:
        text = _read_driver_file(path, out.spec_file, out, "spec-file")
    except FileNotFoundError as err:
        out.add("error", out.spec_file, None, f"The driver specification file could not be found: {err!s}", "spec-file")
        return None
    if isinstance(text, _Unreadable):
        return None
    try:
        # The parser of the load, so that the message is the load's message.
        data = YamlParser().parse(path)
    except (OSError, UnicodeDecodeError) as err:
        out.add("error", out.spec_file, None, f"The file cannot be read: {err}", "spec-file")
        return None
    except ParsingError as err:
        mark = getattr(err.__context__, "problem_mark", None)
        line = mark.line + 1 if mark is not None else None
        out.add("error", out.spec_file, line, str(err), "spec-file")
        return None
    return data, yaml.compose(text, Loader=yaml.SafeLoader)


def _check_spec_file(path: Path, out: _Collector) -> tuple[DriverSpec | None, Node | None, object]:
    parsed = _parse_spec_file(path, out)
    if parsed is None:
        return None, None, None
    data, root = parsed
    try:
        spec = DriverSpecDeserializer().deserialize(data)
    except DeserializationError as err:
        cause = err.__cause__
        if isinstance(cause, PydanticValidationError):
            for loc, message in validation_error_fields(cause):
                out.add("error", out.spec_file, node_line(root, loc), message, "spec-model")
        else:
            out.add("error", out.spec_file, None, str(err), "spec-model")
        return None, root, data
    except InvalidEnvVarNameError as err:
        index = _sequence_index(root, ("spec", "env_vars"), "name", err.name)
        line = node_line(root, ("spec", "env_vars", index, "name")) if index is not None else None
        out.add("error", out.spec_file, line, str(err), "spec-model")
        return None, root, data
    for warning in spec.spec.info.warnings:
        field_name = "icon" if "icon" in warning else "links"
        out.add("warning", out.spec_file, node_line(root, ("spec", "info", field_name)), warning, "load-warning")
    return spec, root, data


def _declared_actions(spec: DriverSpec | None, data: object) -> list[ActionDefinition]:
    """The declared actions: from the model, or, when the model is invalid, each valid raw entry."""
    if spec is not None:
        return list(spec.spec.actions or [])
    spec_data = data.get("spec") if isinstance(data, dict) else None
    raw = spec_data.get("actions") if isinstance(spec_data, dict) else None
    actions: list[ActionDefinition] = []
    for entry in raw if isinstance(raw, list) else []:
        try:
            actions.append(ActionDefinition.model_validate(entry))
        except PydanticValidationError:
            continue
    return actions


def _check_cross_fields(spec: DriverSpec, root: Node | None, out: _Collector) -> None:
    try:
        validate_driver_env_var_docs(spec.spec)
    except DriverEnvVarDocComponentMismatchError as err:
        index = _sequence_index(root, ("spec", "env_vars"), "name", err.name)
        line = node_line(root, ("spec", "env_vars", index)) if index is not None else None
        out.add("error", out.spec_file, line, str(err), "env-var-docs")
    try:
        validate_driver_backup_configs_for_spec(spec.spec)
    except ValidationError as err:
        match = re.match(r"Component '([^']+)'", str(err))
        path: YamlPath = ("spec", "components", match.group(1), "backup") if match else ("spec", "components")
        out.add("error", out.spec_file, node_line(root, path), str(err), "backup")


def _check_template(path: Path, out: _Collector) -> tuple[str, bool]:
    try:
        template = _read_driver_file(path, out.template_file, out, "template-file")
    except FileNotFoundError:
        # The load accepts a driver without a values template and renders "" (the backend's
        # styrmin_backend/services/driver/loaders.py).
        return "", True
    if isinstance(template, _Unreadable):
        return "", False
    environment = get_jinja_environment()
    try:
        template_ast = environment.parse(template)
        environment.from_string(template_ast)
    except jinja2.TemplateSyntaxError as err:
        out.add("error", out.template_file, err.lineno, str(err), "template-syntax")
        return template, False
    for name, lineno in find_retired_filters(template_ast):
        out.add("error", out.template_file, lineno, retired_filter_load_message(name, lineno), "retired-filter")
    return template, True


def _check_actions(actions: list[ActionDefinition], root: Node | None, path: Path, out: _Collector) -> None:
    if not actions:
        return
    try:
        code = _read_driver_file(path, out.actions_file, out, "actions-file")
    except FileNotFoundError:
        out.add(
            "error",
            out.actions_file,
            None,
            f"The actions code file could not be found; {Path(out.spec_file).name} declares actions",
            "actions-file",
        )
        return
    if isinstance(code, _Unreadable):
        return
    try:
        missing = find_missing_entrypoints(code, actions)
    except SyntaxError as err:
        out.add("error", out.actions_file, err.lineno, f"invalid Python: {err.msg}", "actions-syntax")
        return
    for action in missing:
        index = actions.index(action)
        line = node_line(root, ("spec", "actions", index, "location"))
        out.add("error", out.spec_file, line, missing_entrypoint_message(action), "action-entrypoint")


def _build_context(report: CheckReport, root: Node | None, context_data: object | None, out: _Collector) -> None:
    """Build the example context and merge the context file, whatever the state of the template."""
    if report.spec is None:
        return
    try:
        example = build_example_context(report.spec, report.template)
    except (ContextError, ServiceError) as err:
        out.add("error", out.spec_file, None, f"The example context cannot be built: {err!s}", "example-context")
        return
    report.example = example
    for warning in example.warnings:
        out.add("warning", out.spec_file, node_line(root, warning.path), warning.message, "placeholder")
    context = example.context
    if context_data is not None:
        # A ContextFileError reaches the command, which exits with 2.
        context, template_replaced = merge_context_file(context, context_data, report.template)
        if template_replaced:
            out.add(
                "warning",
                out.template_file,
                None,
                "the context file sets app.helm.chart.values_template; the template of the directory is rendered",
                "context-file",
            )
    report.context = context


def _render_template(report: CheckReport, context: GlobalContext, out: _Collector, *, retired_reported: bool) -> None:
    rendered = render_values_checked(report.template, context)
    for use in rendered.undefined:
        out.add("error", out.template_file, use.line, f"undefined variable '{use.name}'", "undefined-variable")
    failure = rendered.failure
    if failure is None:
        report.rendered = rendered
    elif not (failure.kind == "retired-filter" and retired_reported):
        out.add("error", out.template_file, failure.line, failure.message, failure.kind)


def run_checks(
    root: Path,
    *,
    display_root: str | None = None,
    file_names: DriverFileNames | None = None,
    context_data: object | None = None,
    check_actions: bool = True,
) -> CheckReport:
    """Run the checks of a load from a local directory on ``root``, and render its template.

    Every problem is collected. The example context is built, and the context file merged,
    whenever ``driver.styrmin.yml`` is valid; the template is rendered only when its syntax
    is valid too. ``context_data`` is the content of an author's context file.

    Raises:
        ContextFileError: If ``context_data`` cannot be merged or the result is invalid.
    """
    names = file_names or DriverFileNames()
    out = _Collector(display_root if display_root is not None else str(root), names)
    report = CheckReport()

    spec, yaml_root, data = _check_spec_file(root / names.spec_file, out)
    report.spec = spec
    report.template, report.template_valid = _check_template(root / names.values_template, out)
    if check_actions:
        _check_actions(_declared_actions(spec, data), yaml_root, root / names.actions_code, out)
    if spec is not None:
        _check_cross_fields(spec, yaml_root, out)
        _build_context(report, yaml_root, context_data, out)
        if report.template_valid and report.context is not None:
            retired = any(d.check == "retired-filter" for d in out.items)
            _render_template(report, report.context, out, retired_reported=retired)

    report.diagnostics = out.sorted()
    return report
