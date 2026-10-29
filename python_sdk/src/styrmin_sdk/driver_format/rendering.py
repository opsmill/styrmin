"""The Jinja environment of a driver's values template, and the render of the Helm values.

The agent renders a deployment's values with ``render_values`` (ADR-0089).
"""

import functools
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Literal, NoReturn, cast

import jinja2
from jinja2.filters import do_default
from jinja2.tests import test_defined, test_undefined
from jinja2.utils import missing
from pydantic import BaseModel, RootModel
from yaml import YAMLError, safe_load

from styrmin_sdk.driver_format.context.fqdn import to_fqdn_label
from styrmin_sdk.driver_format.context.models.contexts import GlobalContext
from styrmin_sdk.driver_format.errors import (
    CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL,
    ChartValuesTemplateRenderingError,
    InvalidChartValuesError,
    RetiredTemplateFilterError,
)


def split_string(value: str, separator: str | None = None) -> list[str]:
    """Split a string into a list."""
    return value.split(separator)


def component_env_vars(*args: object, **kwargs: object) -> NoReturn:  # noqa: ARG001
    """Retired filter: Styrmin injects env vars by post-render patch (017 FR-007).

    Stays registered so a driver still calling it gets the typed error.
    """
    raise RetiredTemplateFilterError


def component_command(*args: object, **kwargs: object) -> NoReturn:  # noqa: ARG001
    """Retired filter: Styrmin applies ``command`` by post-render patch (022 FR-005).

    Stays registered so a driver still calling it gets the typed error.
    """
    raise RetiredTemplateFilterError(
        filter_name="component_command",
        migration_guide=CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL,
    )


def component_args(*args: object, **kwargs: object) -> NoReturn:  # noqa: ARG001
    """Retired filter: Styrmin applies ``args`` by post-render patch (022 FR-005).

    Stays registered so a driver still calling it gets the typed error.
    """
    raise RetiredTemplateFilterError(
        filter_name="component_args",
        migration_guide=CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL,
    )


def get_jinja_environment(**kwargs: object) -> jinja2.Environment:
    """Create a Jinja2 environment with all custom filters registered."""
    env = jinja2.Environment(**kwargs)  # type: ignore[arg-type]
    env.filters["to_fqdn_label"] = to_fqdn_label
    env.filters["split"] = split_string
    env.filters["component_env_vars"] = component_env_vars
    env.filters["component_command"] = component_command
    env.filters["component_args"] = component_args
    return env


class SilentUndefined(jinja2.Undefined):
    """
    Dont break pageloads because vars arent there!
    """

    def _fail_with_undefined_error(self, *args: object, **kwargs: object) -> str:  # ty: ignore[invalid-method-override]  # noqa: ARG002, PLR6301
        return ""


def render_values(values_template: str, context: GlobalContext) -> dict:
    """Render the value template with the given context.

    Args:
        value_template (str): The value template to render.
        context (GlobalContext): The context to render the value template with.

    Returns:
        dict: The rendered value template.

    Rendering contract surfaced to driver templates:
        The Jinja rendering dict is produced by
        ``GlobalContext.model_dump(exclude_none=True)``. Driver
        ``values_template`` files consume the resolved env vars through
        two stable, named paths on this dict:

        - ``instance.config.env_vars`` (``dict[str, str]`` | absent) —
          the deployment-effective merged env vars (environment-scope
          values overlaid with deployment-scope values per the
          deepest-wins precedence in 008-deployment-env-vars).
        - ``components[<name>].env_vars.config`` (``dict[str, str]`` |
          absent) — the per-component effective merged env vars
          (env → deployment → component layers combined).

        Both paths use ``model_dump(exclude_none=True)`` semantics: the
        ``env_vars`` (and per-component ``env_vars.config``) keys are
        absent from the dict whenever no env vars are set at the
        relevant scope.

        These paths are read-only data (e.g. to build a ConfigMap).
        Styrmin injects env vars into each component's declared
        component container by post-render patch, not through the values
        template (see :meth:`build_component_container_post_rendering_patches` and
        ``dev/guides/driver-env-var-consumption.md``).

        ``ingress_class`` is template data in both modes, with or without
        a dedicated ingress controller. Driver templates do not need to
        set the Ingress class, because Styrmin sets it, or removes it
        with a dedicated ingress controller, after the chart renders (see
        ``IngressUtility.build_app_post_rendering_patches``).
    """
    # Turn the context model into a dict
    context_dict: dict = context.model_dump(exclude_none=True)

    # Render the value template using jinja
    environment = get_jinja_environment(undefined=SilentUndefined)
    template = environment.from_string(values_template)

    try:
        # TODO: Remove the temporary silencing of the UndefinedError
        values = template.render(context_dict)
    except jinja2.TemplateRuntimeError as e:
        raise ChartValuesTemplateRenderingError(f"Chart values template rendering failed: {e!s}") from e

    try:
        return safe_load(values)
    except YAMLError as e:
        raise InvalidChartValuesError(f"The chart values are not valid YAML: {e!s}") from e


# The check render of styrmin-driver: the undefined variables that it finds, with their line.


@dataclass(frozen=True)
class UndefinedUse:
    """A use of a variable that is neither a field of the context model nor a key of the context."""

    line: int | None
    name: str


@dataclass(frozen=True)
class RenderFailure:
    """Why a check render produced no values, with the template line when it is known.

    ``kind`` is ``render`` (the template failed while rendering), ``retired-filter`` (it
    called a filter that Styrmin removed) or ``values-yaml`` (the rendered text is not YAML).
    """

    kind: Literal["render", "retired-filter", "values-yaml"]
    message: str
    line: int | None


@dataclass(frozen=True)
class RenderResult:
    """The output of a check render.

    ``values`` is None when ``failure`` is set. ``undefined`` holds every undefined use found
    before the render ended, also when it failed.
    """

    text: str
    values: Any
    undefined: tuple[UndefinedUse, ...]
    failure: RenderFailure | None = None


class _KnownMapping(dict):  # noqa: FURB189 - Jinja's tojson and mapping tests need a real dict
    """A mapping of the context that knows its path and the names that a template may read.

    For a mapping dumped from a Pydantic model, the known names are the model's fields, so a
    field without a value is known although ``exclude_none`` left it out. For any other
    mapping, they are its keys.
    """

    __slots__ = ("_known", "_path")

    def __init__(self, path: str, known: frozenset[str]) -> None:
        super().__init__()
        self._path = path
        self._known = known


def _child_path(path: str, key: object) -> str:
    return f"{path}.{key}" if path else str(key)


def _wrap(value: object, dumped: object, path: str) -> object:
    """Wrap ``dumped`` (the dump of ``value``) in mappings that know their path and known names."""
    if isinstance(value, RootModel):
        return _wrap(value.root, dumped, path)
    if isinstance(dumped, dict):
        known: set[str] = {str(key) for key in dumped}
        if isinstance(value, BaseModel):
            known |= set(type(value).model_fields) | set(type(value).model_computed_fields)
        mapping = _KnownMapping(path, frozenset(known))
        for key, item in dumped.items():
            if isinstance(value, BaseModel):
                source = getattr(value, str(key), None)
            elif isinstance(value, dict):
                source = value.get(key)
            else:
                source = None
            mapping[key] = _wrap(source, item, _child_path(path, key))
        return mapping
    if isinstance(dumped, list):
        sources = value if isinstance(value, list) and len(value) == len(dumped) else [None] * len(dumped)
        return [_wrap(s, d, f"{path}[{i}]") for i, (s, d) in enumerate(zip(sources, dumped, strict=True))]
    return dumped


def _template_line() -> int | None:
    """The template line that is rendering, from the first frame of compiled template code."""
    frame = sys._getframe(1)
    while frame is not None:
        template = frame.f_globals.get("__jinja_template__")
        if template is not None:
            return template.get_corresponding_lineno(frame.f_lineno)
        frame = frame.f_back
    return None


def _failure_line(error: BaseException) -> int | None:
    """The template line of a render failure, from the traceback that Jinja rewrites."""
    line = None
    tb = error.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == "<template>":
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


# The values of the check render are named as the agent's, so that a message that names the
# class of a value, such as ``'dict object' has no attribute 'x'`` or ``bad operand type for
# abs(): 'SilentUndefined'``, is the agent's message.
_KnownMapping.__module__, _KnownMapping.__name__, _KnownMapping.__qualname__ = "builtins", "dict", "dict"


def _is_undefined(value: object) -> bool:
    # On the agent, every undefined value is a ``SilentUndefined``, and any two are equal.
    return isinstance(value, (_KnownAbsent, _CheckingUndefined))


def _is_dunder(name: str) -> bool:
    return name[:2] == "__" and name[-2:] == "__"


class _KnownAbsent(SilentUndefined):
    """An undefined value of the agent that is not a use to record. It behaves as on the agent.

    For example a field of the context model without a value, an undefined value that Jinja
    makes itself, such as ``loop.previtem`` on the first item, or a name read on the empty
    string that the agent gives for a name read on an undefined value.
    """

    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        return _is_undefined(other)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return id(SilentUndefined)


_KnownAbsent.__name__ = _KnownAbsent.__qualname__ = SilentUndefined.__name__


class _CheckingUndefined(SilentUndefined):
    """The agent's ``SilentUndefined``, which also records each use of an unknown name in ``_uses``.

    Each method gives the agent's result, or fails as on the agent. A use is recorded when the
    render reads the value: writes it out, tests it, loops over it, compares it, uses it in an
    operation, calls it, or reads an item or a name of it. ``render_values_checked`` also
    records an unknown name passed to a filter, a test, a function or a method. A use that
    reads none of these, such as ``x in mapping``, is not recorded.

    A name that the context model knows, such as a field without a value, and an undefined
    value that Jinja makes itself get a ``_KnownAbsent`` instead. ``_for_render`` makes a
    subclass with its own ``_root_known`` and ``_uses`` for one render.
    """

    __slots__ = ()
    _root_known: frozenset[str] = frozenset()
    _uses: list[UndefinedUse]

    @classmethod
    def _for_render(cls, root_known: frozenset[str], uses: list[UndefinedUse]) -> type[jinja2.Undefined]:
        return type(SilentUndefined.__name__, (cls,), {"__slots__": (), "_root_known": root_known, "_uses": uses})

    def __new__(cls, *args: object, **kwargs: object) -> jinja2.Undefined:
        obj = kwargs.get("obj", args[1] if len(args) > 1 else missing)
        name = kwargs.get("name", args[2] if len(args) > 2 else None)
        if isinstance(name, jinja2.Undefined):
            # An undefined key or index, such as ``s[x]``: the use is the key's.
            if isinstance(name, _CheckingUndefined):
                name._record()
            return _KnownAbsent(*args, **kwargs)
        if name is None or isinstance(obj, jinja2.Undefined) or (isinstance(obj, str) and not obj):
            # Jinja's own undefined values (a hint and no name), and a name read on the empty
            # string that the agent gives for a name read on an undefined value, whose use is
            # recorded. A name read on an empty string of the context is not recorded either.
            return _KnownAbsent(*args, **kwargs)
        if obj is missing:
            known = cls._root_known
        elif isinstance(obj, _KnownMapping):
            known = obj._known
        else:
            known = frozenset()
        if isinstance(name, str) and name in known:
            return _KnownAbsent(*args, **kwargs)
        return super().__new__(cls)

    def _label(self) -> str:
        obj, name = self._undefined_obj, self._undefined_name
        if obj is missing:
            return str(name)
        if isinstance(obj, _KnownMapping):
            return _child_path(obj._path, name)
        return f"<{type(obj).__name__}>.{name}"

    def _record(self) -> None:
        use = UndefinedUse(line=_template_line(), name=self._label())
        if use not in self._uses:
            self._uses.append(use)

    def _record_and_fail(self, *args: object, **kwargs: object) -> NoReturn:  # noqa: ARG002
        self._record()
        jinja2.Undefined._fail_with_undefined_error(self)

    def __getattr__(self, name: str) -> object:
        if _is_dunder(name):
            raise AttributeError(name)
        # A name read on an undefined value: the agent gives an empty string, and the use is
        # the undefined value's, the first missing name.
        self._record()
        return super().__getattr__(name)

    def __str__(self) -> str:
        self._record()
        return super().__str__()

    def __repr__(self) -> str:
        self._record()
        return super().__repr__()

    def __bool__(self) -> bool:
        self._record()
        return super().__bool__()

    def __iter__(self) -> Iterator[object]:
        self._record()
        return super().__iter__()

    def __len__(self) -> int:
        self._record()
        return super().__len__()

    def __eq__(self, other: object) -> bool:
        self._record()
        return _is_undefined(other)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return id(SilentUndefined)

    # ``jinja2.Undefined`` binds these to its own failure method when the class is defined
    # (jinja2/runtime.py, class Undefined). They fail as on the agent, after the record.
    __add__ = __radd__ = __sub__ = __rsub__ = _record_and_fail
    __mul__ = __rmul__ = __div__ = __rdiv__ = _record_and_fail
    __truediv__ = __rtruediv__ = _record_and_fail
    __floordiv__ = __rfloordiv__ = _record_and_fail
    __mod__ = __rmod__ = _record_and_fail
    __pos__ = __neg__ = _record_and_fail
    __call__ = __getitem__ = _record_and_fail
    __lt__ = __le__ = __gt__ = __ge__ = _record_and_fail
    __int__ = __float__ = __complex__ = _record_and_fail
    __pow__ = __rpow__ = _record_and_fail


def _record_undefined(args: tuple[object, ...], kwargs: dict[str, object]) -> None:
    for value in (*args, *kwargs.values()):
        if isinstance(value, _CheckingUndefined):
            value._record()


def _recording(func: Callable[..., object]) -> Callable[..., object]:
    """``func``, a filter or a test, which first records each unknown name passed to it.

    Many filters and tests read nothing of the value, such as ``items``, ``pprint``, ``abs`` or
    ``none``. The result, or the failure, is the agent's.
    """

    # ``functools.wraps`` keeps ``jinja_pass_arg``, so Jinja still passes the context to ``func``.
    @functools.wraps(func)
    def recorded(*args: object, **kwargs: object) -> object:
        _record_undefined(args, kwargs)
        return func(*args, **kwargs)

    return recorded


class _CheckingContext(jinja2.runtime.Context):
    """A context whose calls first record each unknown name passed to a function or a method.

    The result, or the failure, is the agent's. A macro is not checked here: a use inside it
    is recorded where the macro uses it.
    """

    def call(self, obj: Callable[..., object], /, *args: object, **kwargs: object) -> object:
        if not isinstance(obj, jinja2.runtime.Macro):
            _record_undefined(args, kwargs)
        return super().call(obj, *args, **kwargs)


def _checked_json_default(value: object) -> object:
    # ``tojson`` calls this for a value that JSON cannot hold, such as an undefined value in a
    # list. It fails as on the agent, after the record.
    if isinstance(value, _CheckingUndefined):
        value._record()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def render_values_checked(values_template: str, context: GlobalContext) -> RenderResult:
    """Render a values template as ``render_values`` does, and record the undefined uses it finds.

    The undefined values are the agent's, which also record their uses (``_CheckingUndefined``),
    so the render fails where the agent's render fails, with its message. A variable is
    undefined when its name is neither a field of the context model nor a key of the
    context. A field without a value is not recorded. Each filter, test, function and method
    records an undefined variable passed to it, apart from the ``default`` filter and the
    ``defined`` and ``undefined`` tests. For a template without undefined variables, the
    values equal those of ``render_values`` for the same context.

    A render that fails does not raise: ``RenderResult.failure`` says why, with the template
    line when it is known, whatever the exception, and the undefined uses found before the
    failure are kept.
    """
    dumped = context.model_dump(exclude_none=True)
    wrapped = _wrap(context, dumped, "")
    if not isinstance(wrapped, _KnownMapping):
        raise TypeError("The context dump is not a mapping")
    uses: list[UndefinedUse] = []
    environment = get_jinja_environment(undefined=_CheckingUndefined._for_render(wrapped._known, uses))
    environment.context_class = _CheckingContext
    # Each environment has its own copy of the filters and tests, so the agent's are unchanged.
    environment.filters.update(
        {name: _recording(func) for name, func in environment.filters.items() if func is not do_default}
    )
    # Jinja types its tests by their arguments; each one takes a value and gives a bool.
    cast("dict[str, Callable[..., object]]", environment.tests).update(
        {
            name: _recording(func)
            for name, func in environment.tests.items()
            if func not in {test_defined, test_undefined}
        }
    )
    # A new dict: Jinja copies its default policies shallowly, so this one is shared.
    environment.policies["json.dumps_kwargs"] = {
        **environment.policies["json.dumps_kwargs"],
        "default": _checked_json_default,
    }
    template = environment.from_string(values_template)
    try:
        text = template.render(wrapped)
    except RetiredTemplateFilterError as e:
        failure = RenderFailure(kind="retired-filter", message=str(e), line=_failure_line(e))
        return RenderResult(text="", values=None, undefined=tuple(uses), failure=failure)
    except Exception as e:  # noqa: BLE001 - every failure of a template becomes a diagnostic
        detail = str(e) if isinstance(e, jinja2.TemplateError) else f"{type(e).__name__}: {e}"
        failure = RenderFailure(
            kind="render", message=f"Chart values template rendering failed: {detail}", line=_failure_line(e)
        )
        return RenderResult(text="", values=None, undefined=tuple(uses), failure=failure)
    try:
        values = safe_load(text)
    except YAMLError as e:
        failure = RenderFailure(kind="values-yaml", message=f"The chart values are not valid YAML: {e!s}", line=None)
        return RenderResult(text=text, values=None, undefined=tuple(uses), failure=failure)
    return RenderResult(text=text, values=values, undefined=tuple(uses))
