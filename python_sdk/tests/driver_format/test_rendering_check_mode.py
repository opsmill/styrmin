"""The check render: every undefined variable with its line and name (research R-003 and R-004)."""

import pytest
from styrmin_sdk.driver_format.example_context import build_example_context
from styrmin_sdk.driver_format.models.structure.directory import DriverDirectory
from styrmin_sdk.driver_format.reading.files import get_resource_file_loader
from styrmin_sdk.driver_format.rendering import render_values, render_values_checked

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


def test_uses_in_operations_calls_subscripts_and_comparisons_are_all_reported() -> None:
    template = (
        "a: '{{ parameters.missing_one }}'\n"
        "b: '{{ parameters.missing_two + 1 }}'\n"
        "c: '{{ parameters.missing_three[\"x\"] }}'\n"
        "d: '{{ parameters.missing_four() }}'\n"
        "e: '{% if parameters.missing_five < 3 %}y{% endif %}'\n"
        "f: '{{ parameters.missing_six | int }}'\n"
        "g: '{{ parameters.missing_seven }}'\n"
    )

    assert _uses(template) == [
        (1, "parameters.missing_one"),
        (2, "parameters.missing_two"),
        (3, "parameters.missing_three"),
        (4, "parameters.missing_four"),
        (5, "parameters.missing_five"),
        (6, "parameters.missing_six"),
        (7, "parameters.missing_seven"),
    ]


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


def test_uses_through_the_items_and_tojson_filters_are_reported() -> None:
    template = (
        "a: '{% for k, v in parameters.typo_items | items %}{{ k }}{% endfor %}'\n"
        "b: '{{ parameters.typo_json | tojson }}'\n"
        "c: '{{ [parameters.typo_list] | tojson }}'\n"
        "d: '{{ parameters.typo_last }}'\n"
    )

    assert _uses(template) == [
        (1, "parameters.typo_items"),
        (2, "parameters.typo_json"),
        (3, "parameters.typo_list"),
        (4, "parameters.typo_last"),
    ]


def test_items_and_tojson_on_fields_without_a_value_render_as_on_the_agent() -> None:
    _spec, _template, context = _example("simple-app")
    loop = "a: '[{% for k, v in instance.config.env_vars | items %}{{ k }}{% endfor %}]'\n"
    json = "a: '{{ instance.config.fqdn_suffix | tojson }}'\n"

    checked_loop = render_values_checked(loop, context)
    checked_json = render_values_checked(json, context)

    assert not checked_loop.undefined
    assert checked_loop.values == render_values(loop, context) == {"a": "[]"}
    assert not checked_json.undefined
    assert checked_json.failure is not None
    with pytest.raises(TypeError) as agent_error:
        render_values(json, context)
    assert checked_json.failure.message == f"Chart values template rendering failed: TypeError: {agent_error.value}"
