"""The check render: the undefined variables that it finds, with their line and name (research R-003 and R-004)."""

from collections.abc import Iterator

import jinja2
import pytest
from styrmin_sdk.driver_format.errors import ChartValuesTemplateRenderingError
from styrmin_sdk.driver_format.example_context import build_example_context
from styrmin_sdk.driver_format.models.structure.directory import DriverDirectory
from styrmin_sdk.driver_format.reading.files import get_resource_file_loader
from styrmin_sdk.driver_format.rendering import (
    _CHECK_RENDER,  # noqa: PLC2701 — testing the render state
    _CheckRender,  # noqa: PLC2701 — testing the render state
    _wrap,  # noqa: PLC2701 — testing the render state
    render_values,
    render_values_checked,
)

from .conftest import EXAMPLE_NAMES, EXAMPLES


def _example(name: str):
    spec = get_resource_file_loader(DriverDirectory(EXAMPLES / name).driver_spec).load()
    template = (EXAMPLES / name / "values.j2.yml").read_text(encoding="utf-8")
    return spec, template, build_example_context(spec, template).context


def _uses(template: str) -> list[tuple[int | None, str]]:
    _spec, _template, context = _example("simple-app")
    return [(u.line, u.name) for u in render_values_checked(template, context).undefined]


def test_each_undefined_use_is_reported_once_with_its_line_and_full_name() -> None:
    template = (
        "a: '{{ parameters.admn_email }}'\n"
        "b: '{{ parameters[\"bad key\"] }}'\n"
        "c: '{% if services[\"simple-app\"].portt %}x{% endif %}'\n"
        "d: '{{ services[\"simple-app\"].port }}'\n"
        "e: '{{ parameters.x.y | default(\"ok\") }}'\n"
        "f: '{% if parameters.mode == \"a\" %}x{% endif %}'\n"
        "g: '{{ parameters | tojson }}'\n"
        "h: '{% for k, v in labels.items() %}{{ k }}{% endfor %}'\n"
        "i: '{{ parameters.admn_email }}'\n"
    )

    assert _uses(template) == [
        (1, "parameters.admn_email"),
        (2, "parameters.bad key"),
        (3, "services.simple-app.portt"),
        (5, "parameters.x"),
        (6, "parameters.mode"),
        (9, "parameters.admn_email"),
    ]


def test_is_defined_and_default_are_not_uses() -> None:
    template = (
        "a: '{% if parameters.helth_path is defined %}x{% endif %}'\n"
        "b: '{{ parameters.helth_path | default(\"/\") }}'\n"
        "c: '{{ nope | default(1) }}'\n"
        "d: '{{ nope | d(1) }}'\n"
        "e: '{% if nope is undefined %}x{% endif %}'\n"
    )

    assert _uses(template) == []


def test_a_field_of_the_context_model_without_a_value_renders_as_on_the_agent() -> None:
    _spec, _template, context = _example("simple-app")
    template = (
        "a: '[{{ instance.config.fqdn_suffix }}]'\n"
        "b: '{% if instance.config.fqdn_suffix %}y{% else %}n{% endif %}'\n"
        "c: '{{ instance.config.external_url_scheme or \"https\" }}'\n"
        "d: '{{ instance.config.external_url_port }}'\n"
        "e: '[{{ instance.config.fqdn_sufix }}]'\n"
        "f: '{% if parameters.helth_path %}y{% else %}n{% endif %}'\n"
    )

    checked = render_values_checked(template, context)

    assert checked.values == render_values(template, context)
    assert checked.values == {"a": "[]", "b": "n", "c": "https", "d": "", "e": "[]", "f": "n"}
    assert [(u.line, u.name) for u in checked.undefined] == [
        (5, "instance.config.fqdn_sufix"),
        (6, "parameters.helth_path"),
    ]


def test_a_top_level_field_without_a_value_is_not_an_error() -> None:
    _spec, _template, context = _example("simple-app")
    context.components = None

    checked = render_values_checked("a: '{% if components %}y{% else %}n{% endif %}'\n", context)

    assert not checked.undefined
    assert checked.values == {"a": "n"}


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_check_render_gives_the_values_of_the_agent_render(name: str) -> None:
    _spec, template, context = _example(name)

    assert render_values_checked(template, context).values == render_values(template, context)


@pytest.mark.parametrize(
    "expression",
    [
        "{{ X }}",
        "{{ X + 1 }}",
        '{{ X["x"] }}',
        "{{ X() }}",
        "{% if X < 3 %}y{% endif %}",
        "{{ X | int }}",
        "{{ X.y.z }}",
    ],
)
def test_a_use_in_an_operation_a_call_or_a_subscript_is_reported(expression: str) -> None:
    assert _uses(f"a: '{expression.replace('X', 'parameters.missing')}'\n") == [(1, "parameters.missing")]


def test_jinja_own_undefined_values_render_as_on_the_agent() -> None:
    _spec, _template, context = _example("simple-app")
    template = (
        "a: '{% for c in [1, 2] %}{% if loop.previtem %}p{% endif %}{% if loop.nextitem %}n{% endif %}{% endfor %}'\n"
    )

    checked = render_values_checked(template, context)

    assert not checked.undefined
    assert checked.failure is None
    assert checked.values == render_values(template, context) == {"a": "np"}


def test_an_operation_on_a_field_without_a_value_fails_as_on_the_agent() -> None:
    _spec, _template, context = _example("simple-app")
    template = "a: '{{ instance.config.fqdn_suffix + 1 }}'\n"

    checked = render_values_checked(template, context)

    assert not checked.undefined
    assert checked.failure is not None
    assert checked.failure.kind == "render"
    assert checked.failure.line == 1
    assert checked.failure.message == (
        "Chart values template rendering failed: 'dict object' has no attribute 'fqdn_suffix'"
    )


@pytest.mark.parametrize(
    ("template", "line", "detail"),
    [
        ("a: 1\nb: '{{ 1 + \"x\" }}'\n", 2, "TypeError:"),
        ("a: 1\nb: 2\nc: '{{ 1 // 0 }}'\n", 3, "ZeroDivisionError:"),
        ("a: '{% include \"other.j2\" %}'\n", 1, "no loader for this environment specified"),
    ],
)
def test_any_render_failure_is_a_result_with_its_line(template: str, line: int, detail: str) -> None:
    _spec, _template, context = _example("simple-app")

    checked = render_values_checked(template, context)

    assert checked.values is None
    assert checked.failure is not None
    assert checked.failure.kind == "render"
    assert checked.failure.line == line
    assert detail in checked.failure.message


def test_undefined_uses_found_before_a_render_failure_are_kept() -> None:
    _spec, _template, context = _example("simple-app")
    template = "a: '{{ parameters.typo }}'\nb: '{{ 1 // 0 }}'\n"

    checked = render_values_checked(template, context)

    assert [(u.line, u.name) for u in checked.undefined] == [(1, "parameters.typo")]
    assert checked.failure is not None
    assert checked.failure.line == 2


def _agent_failure(template: str, context) -> str:
    """The message of the agent's render failure, as ``check`` reports it."""
    try:
        render_values(template, context)
    except ChartValuesTemplateRenderingError as error:
        return str(error)
    except Exception as error:  # noqa: BLE001 - the agent's render raises what the template raises
        return f"Chart values template rendering failed: {type(error).__name__}: {error}"
    raise AssertionError("the agent's render did not fail")


# The agent renders each of these with no message. X is the undefined variable.
_USES_THAT_THE_AGENT_RENDERS_WITH_NO_MESSAGE = [
    "{% for k, v in X | items %}{{ k }}{% endfor %}",
    "{{ X | pprint }}",
    "{{ X | select | list }}",
    '{{ X | map("upper") | list }}',
    "{{ X | length }}",
    "{% if X is none %}y{% endif %}",
    "{% if X is string %}y{% endif %}",
    "{{ [X] }}",
    "{{ [1, 2][X] }}",
    '{% set s = {"k": 1} %}{{ s[X] }}',
    '{{ {"k": 1}.get(X) }}',
    "{{ dict(k=X) | length }}",
    "{{ X.y }}",
]


@pytest.mark.parametrize("expression", _USES_THAT_THE_AGENT_RENDERS_WITH_NO_MESSAGE)
def test_a_use_that_the_agent_renders_with_no_message_is_reported_and_renders_as_on_the_agent(
    expression: str,
) -> None:
    _spec, _template, context = _example("simple-app")
    template = f"a: '{expression.replace('X', 'parameters.typo')}'\n" + "b: '{{ parameters.typo_last }}'\n"

    checked = render_values_checked(template, context)

    assert [(u.line, u.name) for u in checked.undefined] == [(1, "parameters.typo"), (2, "parameters.typo_last")]
    assert checked.failure is None
    assert checked.values == render_values(template, context)


# The agent's render fails on each of these, with a message that gives no line. X is the
# undefined variable.
_USES_THAT_THE_AGENT_FAILS_ON = [
    "{{ X + 1 }}",
    "{{ X | int }}",
    "{{ X | tojson }}",
    "{{ [X] | tojson }}",
    "{{ X | abs }}",
    "{{ X | round }}",
    "{{ X | indent(2) }}",
    '{{ "a,b" | split(X) }}',
    "{% for i in range(X) %}x{% endfor %}",
    '{{ "abc".startswith(X) }}',
    '{{ "abc".replace(X, "x") }}',
    '{{ "{}{}".format(X) }}',
    '{{ X.split(":")[0] }}',
    "{{ X.y + 1 }}",
]


@pytest.mark.parametrize("expression", _USES_THAT_THE_AGENT_FAILS_ON)
def test_a_use_that_the_agent_fails_on_is_reported_and_fails_as_on_the_agent(expression: str) -> None:
    _spec, _template, context = _example("simple-app")
    template = f"a: '{expression.replace('X', 'parameters.typo')}'\n" + "b: '{{ parameters.typo_last }}'\n"

    checked = render_values_checked(template, context)

    assert [(u.line, u.name) for u in checked.undefined] == [(1, "parameters.typo")]
    assert checked.failure is not None
    assert checked.failure.kind == "render"
    assert checked.failure.line == 1
    assert checked.failure.message == _agent_failure(template, context)


def test_a_retired_filter_given_an_undefined_variable_still_fails_with_its_error() -> None:
    _spec, _template, context = _example("simple-app")

    checked = render_values_checked("a: '{{ parameters.typo | component_command }}'\n", context)

    assert [(u.line, u.name) for u in checked.undefined] == [(1, "parameters.typo")]
    assert checked.failure is not None
    assert checked.failure.kind == "retired-filter"
    assert checked.failure.line == 1


def test_filters_on_fields_without_a_value_render_or_fail_as_on_the_agent() -> None:
    _spec, _template, context = _example("simple-app")
    loop = "a: '[{% for k, v in instance.config.env_vars | items %}{{ k }}{% endfor %}]'\n"
    failing = [
        "a: '{{ instance.config.fqdn_suffix | tojson }}'\n",
        "a: '{{ instance.config.external_url_port | abs }}'\n",
        "a: '{{ instance.config.external_url_port | round }}'\n",
        "a: '{% for i in range(instance.config.external_url_port) %}x{% endfor %}'\n",
    ]

    checked_loop = render_values_checked(loop, context)

    assert not checked_loop.undefined
    assert checked_loop.values == render_values(loop, context) == {"a": "[]"}
    for template in failing:
        checked = render_values_checked(template, context)
        assert not checked.undefined
        assert checked.failure is not None
        with pytest.raises(TypeError) as agent_error:
            render_values(template, context)
        assert checked.failure.message == f"Chart values template rendering failed: TypeError: {agent_error.value}"


# The agent renders each of these without failing. X is the undefined variable; Y is read only
# in the branch that the agent does not take.
_BRANCHES_AFTER_AN_UNDEFINED_VARIABLE = [
    "{% if X | length == 0 %}empty{% else %}{{ Y }}{% endif %}",
    "{% if X | list == [] %}empty{% else %}{{ Y }}{% endif %}",
    "{% if X is iterable %}iterable{% else %}{{ Y }}{% endif %}",
    "{% if X is sequence %}sequence{% else %}{{ Y }}{% endif %}",
    "{% if X == '' %}{{ Y }}{% else %}not empty{% endif %}",
    "{% if [1, 2][X] == 1 %}{{ Y }}{% else %}undefined{% endif %}",
    "{% if X | pprint == 'Undefined' %}undefined{% else %}{{ Y }}{% endif %}",
    "{% if X.y is string %}string{% else %}{{ Y }}{% endif %}",
    "{% if X.y == '' %}empty{% else %}{{ Y }}{% endif %}",
    "{% if X.y is defined %}defined{% else %}{{ Y }}{% endif %}",
    "{% if X.y | pprint == \"''\" %}empty{% else %}{{ Y }}{% endif %}",
    "{% if X == instance.config.fqdn_suffix %}equal{% else %}{{ Y }}{% endif %}",
    '{% if X.y is sameas "" %}same{% else %}{{ Y }}{% endif %}',
]


@pytest.mark.parametrize("expression", _BRANCHES_AFTER_AN_UNDEFINED_VARIABLE)
def test_after_an_undefined_variable_the_render_takes_the_branch_of_the_agent(expression: str) -> None:
    _spec, _template, context = _example("simple-app")
    template = f'a: "{expression.replace("X", "parameters.typo").replace("Y", "parameters.not_reached")}"\n'

    checked = render_values_checked(template, context)

    assert [(u.line, u.name) for u in checked.undefined] == [(1, "parameters.typo")]
    assert checked.values == render_values(template, context)


def test_a_slice_with_an_undefined_bound_is_not_reported_and_fails_as_on_the_agent() -> None:
    _spec, _template, context = _example("simple-app")
    template = "a: '{{ [1, 2, 3][:parameters.typo] }}'\n"

    checked = render_values_checked(template, context)

    assert not checked.undefined
    assert checked.failure is not None
    assert checked.failure.line == 1
    assert checked.failure.message == _agent_failure(template, context)


def test_an_error_in_a_call_that_receives_an_undefined_variable_is_not_hidden() -> None:
    _spec, _template, context = _example("simple-app")
    template = 'a: \'{% set d = {} %}{{ d.update(["a"] | map("component_env_vars"), k=parameters.typo) }}\'\n'

    checked = render_values_checked(template, context)

    assert [(u.line, u.name) for u in checked.undefined] == [(1, "parameters.typo")]
    assert checked.failure is not None
    assert checked.failure.kind == "retired-filter"


@pytest.mark.parametrize(
    "expression",
    [
        "{{ [1, 2][instance.config.fqdn_suffix] }}",
        "{{ components[instance.config.fqdn_suffix] }}",
        "{% for i in [1] %}{{ components[loop.previtem] }}{% endfor %}",
        "{{ instance.config.fqdn_suffix.a.b }}",
    ],
)
def test_a_field_without_a_value_or_a_jinja_undefined_value_as_a_key_or_a_parent_is_not_reported(
    expression: str,
) -> None:
    _spec, _template, context = _example("simple-app")
    template = f"a: '{expression}'\n"

    checked = render_values_checked(template, context)

    assert not checked.undefined
    assert checked.failure is None
    assert checked.values == render_values(template, context)


# Filters that Jinja passes the context, the evaluation context or the environment to.
_FILTERS_THAT_TAKE_THE_CONTEXT_OR_THE_ENVIRONMENT = [
    "{{ [{'a': 1}, {'a': 2}] | map(attribute='a') | sum }}",
    "{{ [{'a': 1}, {'a': 2}] | selectattr('a', 'gt', 1) | list }}",
    "{{ [1, 2, 3] | select('odd') | list }}",
    "{{ [1, 2, 3] | reject('odd') | list }}",
    "{{ [{'a': 1}, {'a': 1}] | groupby('a') | list }}",
    "{{ ['b', 'a'] | sort | join(',') }}",
    "{{ ['b', 'a', 'a'] | unique | list }}",
    "{{ [3, 1] | min }}-{{ [3, 1] | max }}",
    "{{ 'hello world foo' | truncate(9) }}",
    "{{ 'hello world foo' | wordwrap(5) }}",
    "{{ {'a': 1} | xmlattr | replace('\"', '') }}",
    "{{ instance | attr('config') | length }}",
    "{{ components | dictsort | first | first }}",
    "{{ 'upper' is filter }}-{{ 'odd' is test }}",
    "{{ 'Hello' | replace('l', 'L') }}",
]


@pytest.mark.parametrize("expression", _FILTERS_THAT_TAKE_THE_CONTEXT_OR_THE_ENVIRONMENT)
def test_filters_that_take_the_context_or_the_environment_give_the_values_of_the_agent(expression: str) -> None:
    _spec, _template, context = _example("simple-app")
    template = f'a: "{expression}"\n'

    checked = render_values_checked(template, context)

    assert not checked.undefined
    assert checked.failure is None
    assert checked.values == render_values(template, context)


@pytest.mark.parametrize(
    ("expression", "names"),
    [
        ("{% if instance.config.fqdn_suffix == X %}equal{% endif %}", ["parameters.typo"]),
        ("{{ X == Y }}", ["parameters.typo", "parameters.other"]),
        ("{{ X != Y }}", ["parameters.typo", "parameters.other"]),
        ("{{ [X] == [Y] }}", ["parameters.typo", "parameters.other"]),
        ("{{ X is sameas Y }}", ["parameters.typo", "parameters.other"]),
    ],
)
def test_both_values_of_a_comparison_are_reported(expression: str, names: list[str]) -> None:
    _spec, _template, context = _example("simple-app")
    template = f"a: '{expression.replace('X', 'parameters.typo').replace('Y', 'parameters.other')}'\n"

    checked = render_values_checked(template, context)

    assert [(u.line, u.name) for u in checked.undefined] == [(1, name) for name in names]
    assert checked.values == render_values(template, context)


def test_names_that_start_with_an_underscore_render_as_on_the_agent() -> None:
    _spec, _template, context = _example("simple-app")
    context = context.model_copy(update={"parameters": {**context.parameters, "_path": "from-the-context"}})
    template = "a: '{{ parameters._path }}'\nb: '{{ instance._known | length }}'\nc: '{{ parameters.typo._uses }}'\n"

    checked = render_values_checked(template, context)

    assert checked.values == render_values(template, context) == {"a": "from-the-context", "b": "0", "c": ""}
    assert [(u.line, u.name) for u in checked.undefined] == [(2, "instance._known"), (3, "parameters.typo")]


def test_an_undefined_key_is_reported_once_at_the_line_that_reads_it() -> None:
    _spec, _template, context = _example("simple-app")
    template = "{% set v = {}[parameters.typo] %}\na: '{{ v + 1 }}'\n"

    checked = render_values_checked(template, context)

    assert [(u.line, u.name) for u in checked.undefined] == [(1, "parameters.typo")]
    assert checked.failure is not None
    assert checked.failure.line == 2
    assert checked.failure.message == _agent_failure(template, context)


def _dicts(value: object) -> Iterator[dict]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _dicts(item)


def test_the_render_state_holds_each_mapping_of_the_context() -> None:
    # A mapping that a template removes, such as ``instance.pop("config")``, stays alive, so
    # that no dict that the template makes later gets its id and its path.
    _spec, _template, context = _example("simple-app")
    render = _CheckRender()
    wrapped = _wrap(context, context.model_dump(exclude_none=True), "", render.mappings)
    mappings = list(_dicts(wrapped))

    assert len(mappings) > 1
    assert len(render.mappings) == len(mappings)
    assert all(render.mappings[id(mapping)][0] is mapping for mapping in mappings)


@pytest.mark.parametrize(
    "template",
    [
        "a: '{{ \"abc\".nmae }}'\n",
        "a: x\n{% if false %}b: '{{ \"abc\".nmae }}'\n{% endif %}",
        'a: x\n{% macro unused() %}{{ {"k": 1}.zz }}{% endmacro %}',
        "a: x\n{% if true %}{% else %}b: '{{ \"abc\".nmae }}'{% endif %}",
    ],
)
def test_a_name_read_on_a_literal_that_jinja_replaces_with_its_result_when_it_compiles_is_not_reported(
    template: str,
) -> None:
    _spec, _template, context = _example("simple-app")

    checked = render_values_checked(template, context)

    assert not checked.undefined
    assert checked.failure is None
    assert checked.values == render_values(template, context)


@pytest.mark.parametrize(
    "template",
    [
        "a: '{% if \"abc\".nmae %}y{% endif %}'\n",
        "a: '{{ app.version.nmae }}'\n",
        "a: '{{ \"abc\".nmae ~ app.version }}'\n",
    ],
)
def test_a_name_read_on_a_string_is_reported_with_the_type_of_the_value(template: str) -> None:
    _spec, _template, context = _example("simple-app")

    checked = render_values_checked(template, context)

    assert [(u.line, u.name) for u in checked.undefined] == [(1, "<str>.nmae")]
    assert checked.values == render_values(template, context)


def test_a_name_read_on_an_empty_string_of_the_context_is_not_reported() -> None:
    _spec, _template, context = _example("simple-app")
    context = context.model_copy(update={"parameters": {**context.parameters, "empty": ""}})

    template = "a: '{{ parameters.empty.nmae }}'\n"

    checked = render_values_checked(template, context)

    assert not checked.undefined
    assert checked.failure is None
    assert checked.values == render_values(template, context)


def test_a_template_that_does_not_compile_raises_as_on_the_agent() -> None:
    _spec, _template, context = _example("simple-app")
    template = "a: '{{ x'\n"

    with pytest.raises(jinja2.TemplateSyntaxError) as agent_error:
        render_values(template, context)
    with pytest.raises(jinja2.TemplateSyntaxError) as check_error:
        render_values_checked(template, context)
    assert str(check_error.value) == str(agent_error.value)


def test_the_render_state_is_reset_after_a_render_that_fails() -> None:
    _spec, _template, context = _example("simple-app")

    failed = render_values_checked("a: '{{ parameters.typo + 1 }}'\n", context)

    assert failed.failure is not None
    assert _CHECK_RENDER.get() is None
