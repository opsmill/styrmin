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


# The check render of styrmin-driver: each undefined variable that it reaches, with its line.


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


class _KnownAbsent(SilentUndefined):
    """A field of the context model without a value: it renders as on the agent.

    Its messages name the mapping as the agent's do (``'dict object' has no attribute ...``),
    not the internal ``_KnownMapping`` class.
    """

    __slots__ = ()

    @property
    def _undefined_message(self) -> str:
        if isinstance(self._undefined_obj, _KnownMapping):
            return f"'dict object' has no attribute {self._undefined_name!r}"
        return super()._undefined_message


# A TypeError names the class of the value, such as ``bad operand type for abs()``: the agent's.
_KnownAbsent.__name__ = _KnownAbsent.__qualname__ = SilentUndefined.__name__


class _CheckingUndefined(jinja2.Undefined):
    """An ``Undefined`` that records each use of an unknown name in ``_uses``.

    A name that the context model knows, such as a field without a value, and an undefined
    value that Jinja makes itself, such as ``loop.previtem`` on the first item, get a
    ``_KnownAbsent`` instead, so they render as on the agent and are not recorded.
    A use of an unknown name is recorded when the render reads its value: writes it out,
    tests it, loops over it, uses it in an operation, calls it, or reads a subscript or an
    index of it or with it. ``render_values_checked`` also makes each filter, test, function
    and method record an unknown name passed to it. Where the agent's render fails, the
    render goes on with an empty value when it can, to find the next use; a slice such as
    ``s[:x]`` stops it. Some uses read no value and are not recorded, such as
    ``x in mapping``, or ``[x] | length`` on a list that holds ``x``.
    ``_for_render`` makes a subclass with its own ``_root_known`` and ``_uses`` for one render.
    """

    __slots__ = ()
    _root_known: frozenset[str] = frozenset()
    _uses: list[UndefinedUse]

    @classmethod
    def _for_render(cls, root_known: frozenset[str], uses: list[UndefinedUse]) -> type[jinja2.Undefined]:
        # Named as the agent's class, so that a TypeError that names the class is the agent's.
        return type(SilentUndefined.__name__, (cls,), {"__slots__": (), "_root_known": root_known, "_uses": uses})

    def __new__(cls, *args: object, **kwargs: object) -> jinja2.Undefined:
        obj = kwargs.get("obj", args[1] if len(args) > 1 else missing)
        name = kwargs.get("name", args[2] if len(args) > 2 else None)
        if name is None:
            # Jinja's own undefined values (a hint and no name), such as loop.previtem.
            return _KnownAbsent(*args, **kwargs)
        if obj is missing:
            known = cls._root_known
        elif isinstance(obj, _KnownMapping):
            known = obj._known
        else:
            known = frozenset()
        if isinstance(name, str) and name in known:
            return _KnownAbsent(*args, **kwargs)
        if isinstance(name, _CheckingUndefined):
            # An undefined key or index, such as ``s[x]``, for which Jinja gives an undefined
            # value, as on the agent: the use is the key's (see ``_record``).
            name._record()
        return super().__new__(cls)

    def _label(self) -> str:
        obj, name = self._undefined_obj, self._undefined_name
        if obj is missing:
            return str(name)
        if isinstance(obj, _CheckingUndefined):
            return f"{obj._label()}.{name}"
        if isinstance(obj, _KnownMapping):
            return _child_path(obj._path, name)
        return f"<{type(obj).__name__}>.{name}"

    def _record(self) -> None:
        # A name read on an undefined value: its parent, the first missing name, is the use.
        # A value read with an undefined key: the key is the use.
        if isinstance(self._undefined_obj, _CheckingUndefined) or isinstance(self._undefined_name, _CheckingUndefined):
            return
        use = UndefinedUse(line=_template_line(), name=self._label())
        if use not in self._uses:
            self._uses.append(use)

    def _fail_with_undefined_error(self, *args: object, **kwargs: object) -> str:  # ty: ignore[invalid-method-override]  # noqa: ARG002
        self._record()
        return ""

    def _use_as_false(self, *args: object, **kwargs: object) -> bool:  # noqa: ARG002
        self._record()
        return False

    def __getattr__(self, name: str) -> object:
        if name[:1] == "_":
            raise AttributeError(name)
        self._record()
        return type(self)(obj=self, name=name)

    def __str__(self) -> str:
        self._record()
        return ""

    def __repr__(self) -> str:
        # A list or a dict that holds the value renders it with repr, as ``Undefined`` on the agent.
        self._record()
        return "Undefined"

    def __bool__(self) -> bool:
        self._record()
        return False

    def __iter__(self) -> Iterator[object]:
        self._record()
        return iter(())

    def __len__(self) -> int:
        self._record()
        return 0

    def __int__(self) -> int:
        self._record()
        return 0

    def __index__(self) -> NoReturn:
        # A list index and a slice read the value as an index. They fail as on the agent: Jinja
        # then gives an undefined value for an index, and a slice fails.
        self._record()
        raise TypeError(f"{type(self).__name__!r} object cannot be interpreted as an integer")

    def __float__(self) -> float:
        self._record()
        return 0.0

    def __complex__(self) -> complex:
        self._record()
        return 0j

    def __eq__(self, other: object) -> bool:
        self._record()
        return type(self) is type(other)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    __hash__ = jinja2.Undefined.__hash__

    # ``jinja2.Undefined`` binds these to its own failure method when the class is defined,
    # so they must be bound again here to record the use (jinja2/runtime.py, class Undefined).
    __add__ = __radd__ = __sub__ = __rsub__ = _fail_with_undefined_error
    __mul__ = __rmul__ = __div__ = __rdiv__ = _fail_with_undefined_error
    __truediv__ = __rtruediv__ = _fail_with_undefined_error
    __floordiv__ = __rfloordiv__ = _fail_with_undefined_error
    __mod__ = __rmod__ = _fail_with_undefined_error
    __pos__ = __neg__ = _fail_with_undefined_error
    __call__ = __getitem__ = _fail_with_undefined_error
    __pow__ = __rpow__ = _fail_with_undefined_error
    __lt__ = __le__ = __gt__ = __ge__ = _use_as_false


# Filters that raise whatever they receive, so that a driver that calls one gets the typed error.
_RETIRED_FILTERS = frozenset({component_env_vars, component_command, component_args})


def _record_undefined(args: tuple[object, ...], kwargs: dict[str, object]) -> list[_CheckingUndefined]:
    undefined = [value for value in (*args, *kwargs.values()) if isinstance(value, _CheckingUndefined)]
    for value in undefined:
        value._record()
    return undefined


def _empty_after(undefined: _CheckingUndefined, name: str) -> jinja2.Undefined:
    # An empty value that records no use of its own, since its parent's use is recorded. The
    # name is that of the filter or the function; no message shows it.
    return type(undefined)(obj=undefined, name=name)


def _checking_filter(name: str, func: Callable[..., object]) -> Callable[..., object]:
    """``func``, the filter ``name``, which records each unknown name passed to it.

    Some filters do not read the value (``items``, ``pprint``, a filter that returns a
    generator), and others fail with a ``TypeError`` that does not name it (``abs``, ``round``).
    The filter gives its own result, as on the agent, so that an ``if`` on it takes the
    agent's branch; when the filter fails, the result is an empty value, so that the render
    goes on.
    """

    # ``functools.wraps`` keeps ``jinja_pass_arg``, so Jinja still passes the context to ``func``.
    @functools.wraps(func)
    def checked(*args: object, **kwargs: object) -> object:
        undefined = _record_undefined(args, kwargs)
        if not undefined or func in _RETIRED_FILTERS:
            return func(*args, **kwargs)
        try:
            return func(*args, **kwargs)
        except Exception:  # noqa: BLE001 - the use is recorded; the agent's render fails here
            return _empty_after(undefined[0], name)

    return checked


def _checking_test(func: Callable[..., bool]) -> Callable[..., bool]:
    """``func``, which records each unknown name passed to it.

    Most tests, such as ``none`` or ``string``, do not read the value. The test gives its
    own result, as on the agent, or false when it fails.
    """

    @functools.wraps(func)
    def checked(*args: object, **kwargs: object) -> bool:
        if not _record_undefined(args, kwargs):
            return func(*args, **kwargs)
        try:
            return func(*args, **kwargs)
        except Exception:  # noqa: BLE001 - the use is recorded; the agent's render fails here
            return False

    return checked


class _CheckingContext(jinja2.runtime.Context):
    """A context whose calls record each unknown name passed to a function or a method.

    The call gives its own result, as on the agent. When it fails, for example
    ``'abc'.startswith(x)`` or ``range(x)``, the result is an empty value, so that the render
    goes on. A macro is called as on the agent: a use inside it is recorded where the macro
    uses it.
    """

    def call(self, obj: Callable[..., object], /, *args: object, **kwargs: object) -> object:
        undefined = [] if isinstance(obj, jinja2.runtime.Macro) else _record_undefined(args, kwargs)
        if not undefined:
            return super().call(obj, *args, **kwargs)
        try:
            return super().call(obj, *args, **kwargs)
        except Exception:  # noqa: BLE001 - the use is recorded; the agent's render fails here
            return _empty_after(undefined[0], getattr(obj, "__name__", "call"))


def _checked_json_default(value: object) -> object:
    # ``tojson`` calls this for a value that JSON cannot hold, such as an undefined value in a list.
    if isinstance(value, _CheckingUndefined):
        value._record()
        return None
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def render_values_checked(values_template: str, context: GlobalContext) -> RenderResult:
    """Render a values template as ``render_values`` does, and record each undefined use it reaches.

    A variable is undefined when its name is neither a field of the context model nor a key
    of the context. A field without a value renders as on the agent: an empty string that
    tests as false. Each filter, test, function and method records an undefined variable
    passed to it, apart from the ``default`` filter and the ``defined`` and ``undefined``
    tests, and gives its own result, or an empty value where it fails. For a template
    without undefined variables, the values equal those of ``render_values`` for the same
    context.

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
        {name: _checking_filter(name, func) for name, func in environment.filters.items() if func is not do_default}
    )
    # Jinja types its tests by their arguments; each one takes a value and gives a bool.
    cast("dict[str, Callable[..., bool]]", environment.tests).update(
        {
            name: _checking_test(func)
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
