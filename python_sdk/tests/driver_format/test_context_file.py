"""FR-003 and FR-004, research R-008: an author's context file merged into the example context."""

import json
from pathlib import Path

import pytest
import yaml
from styrmin_sdk.driver_format.context.fqdn import compute_primary_fqdn
from styrmin_sdk.driver_format.example_context import EXAMPLE_DEPLOYMENT_ID

from .conftest import EXAMPLES


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def _render(run_cli, driver: Path, context: Path | None = None) -> dict:
    argv = ["render", str(driver)] + (["--context", str(context)] if context else [])
    result = run_cli(*argv)
    assert result.code == 0, result.err
    return yaml.safe_load(result.out)


def _differences(before: object, after: object, path: str = "") -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        keys = sorted(set(before) | set(after))
        return [d for k in keys for d in _differences(before.get(k), after.get(k), f"{path}.{k}")]
    return [] if before == after else [path]


def test_a_file_that_sets_one_parameter_changes_only_its_values(tmp_path: Path, run_cli) -> None:
    context = _write(tmp_path, "ctx.yml", "parameters:\n  image_tag: '9.9.9'\n")

    before = _render(run_cli, EXAMPLES / "generic-app")
    after = _render(run_cli, EXAMPLES / "generic-app", context)

    changed = _differences(before, after)
    assert changed
    assert all("9.9.9" in str(_value(after, path)) for path in changed)


def _value(data: object, path: str) -> object:
    for key in path.strip(".").split("."):
        data = data[key]  # ty: ignore[not-subscriptable]
    return data


def test_nested_mappings_merge_and_lists_replace(tmp_path: Path, run_cli) -> None:
    context = _write(tmp_path, "ctx.yml", "instance:\n  config:\n    fqdn_suffix: apps.example.org\nutilities: []\n")

    result = run_cli("context", str(EXAMPLES / "simple-app"), "--context", str(context))

    data = yaml.safe_load(result.out)
    assert result.code == 0
    assert data["instance"]["config"]["fqdn_suffix"] == "apps.example.org"
    assert data["instance"]["namespace"].startswith("styrmin-")
    assert data["utilities"] == []


def test_a_mistyped_top_level_key_exits_with_2_and_names_it(tmp_path: Path, run_cli) -> None:
    context = _write(tmp_path, "ctx.yml", "parameterz:\n  image_tag: '1.2.3'\n")

    result = run_cli("render", str(EXAMPLES / "generic-app"), "--context", str(context))

    assert result.code == 2
    assert "parameterz" in result.err
    assert not result.out


def test_a_mistyped_nested_key_exits_with_2_and_names_its_path(tmp_path: Path, run_cli) -> None:
    context = _write(tmp_path, "ctx.yml", "instance:\n  config:\n    fqdn_sufix: x\n")

    result = run_cli("check", str(EXAMPLES / "simple-app"), "--context", str(context))

    assert result.code == 2
    assert "instance.config.fqdn_sufix" in result.err


def test_a_file_that_is_not_yaml_exits_with_2(tmp_path: Path, run_cli) -> None:
    context = _write(tmp_path, "ctx.yml", "parameters: [unclosed\n")

    result = run_cli("render", str(EXAMPLES / "simple-app"), "--context", str(context))

    assert result.code == 2
    assert "not valid YAML" in result.err


def test_a_file_whose_top_level_is_a_list_exits_with_2(tmp_path: Path, run_cli) -> None:
    context = _write(tmp_path, "ctx.yml", "- a\n- b\n")

    result = run_cli("render", str(EXAMPLES / "simple-app"), "--context", str(context))

    assert result.code == 2
    assert "the top level must be a mapping" in result.err


def test_a_context_file_that_cannot_be_read_exits_with_2(tmp_path: Path, run_cli) -> None:
    result = run_cli("render", str(EXAMPLES / "simple-app"), "--context", str(tmp_path / "missing.yml"))

    assert result.code == 2
    assert "cannot be read" in result.err


def test_a_full_context_in_json_is_accepted_and_renders_the_same(tmp_path: Path, run_cli) -> None:
    example = yaml.safe_load(run_cli("context", str(EXAMPLES / "simple-app")).out)
    context = _write(tmp_path, "ctx.json", json.dumps(example))

    assert _render(run_cli, EXAMPLES / "simple-app", context) == _render(run_cli, EXAMPLES / "simple-app")


def test_a_values_template_in_the_context_file_is_replaced_with_a_warning(tmp_path: Path, run_cli) -> None:
    context = _write(tmp_path, "ctx.yml", "app:\n  helm:\n    chart:\n      values_template: 'other: 1'\n")

    result = run_cli("render", str(EXAMPLES / "simple-app"), "--context", str(context))

    assert result.code == 0
    assert "the template of the directory is rendered" in result.err
    assert "other" not in yaml.safe_load(result.out)


def test_a_context_file_that_is_not_utf8_exits_with_2(tmp_path: Path, run_cli) -> None:
    context = tmp_path / "ctx.yml"
    context.write_bytes(b"parameters:\n  name: \xff\n")

    result = run_cli("render", str(EXAMPLES / "simple-app"), "--context", str(context))

    assert result.code == 2
    assert "is not valid UTF-8" in result.err


@pytest.mark.parametrize("helm", ["null", "x"])
def test_a_context_file_with_a_wrong_shape_exits_with_2_and_names_the_key(helm: str, tmp_path: Path, run_cli) -> None:
    context = _write(tmp_path, "ctx.yml", f"app:\n  helm: {helm}\n")

    result = run_cli("render", str(EXAMPLES / "simple-app"), "--context", str(context))

    assert result.code == 2
    assert "app.helm" in result.err


def test_a_context_file_with_an_invalid_env_var_name_exits_with_2(tmp_path: Path, run_cli) -> None:
    context = _write(tmp_path, "ctx.yml", "instance:\n  config:\n    env_vars:\n      1BAD: x\n")

    result = run_cli("render", str(EXAMPLES / "simple-app"), "--context", str(context))

    assert result.code == 2
    assert "1BAD" in result.err


def _ingress_host(values: dict) -> str:
    return values["ingress"]["hosts"][0]["host"]


@pytest.mark.parametrize(
    "content",
    [
        "instance:\n  config:\n    fqdn_suffix: apps.example.org\n",
        "cluster:\n  config:\n    fqdn_suffix: apps.example.org\n",
    ],
    ids=["instance config", "cluster config"],
)
def test_an_fqdn_suffix_in_the_context_file_reaches_the_service_fqdns(content: str, tmp_path: Path, run_cli) -> None:
    context = _write(tmp_path, "ctx.yml", content)

    values = _render(run_cli, EXAMPLES / "simple-app", context)
    data = yaml.safe_load(run_cli("context", str(EXAMPLES / "simple-app"), "--context", str(context)).out)

    expected = compute_primary_fqdn("simple-app", str(EXAMPLE_DEPLOYMENT_ID), "apps.example.org")
    assert data["instance"]["config"]["fqdn_suffix"] == "apps.example.org"
    assert data["services"]["simple-app"]["primary_fqdn"] == expected
    assert _ingress_host(values) == expected


def test_services_set_by_the_context_file_are_kept(tmp_path: Path, run_cli) -> None:
    context = _write(
        tmp_path,
        "ctx.yml",
        "instance:\n  config:\n    fqdn_suffix: apps.example.org\n"
        "services:\n  simple-app:\n    primary_fqdn: given.example.org\n",
    )

    values = _render(run_cli, EXAMPLES / "simple-app", context)

    assert _ingress_host(values) == "given.example.org"


def test_warnings_about_values_that_the_context_file_sets_are_left_out(tmp_path: Path, run_cli) -> None:
    context = _write(tmp_path, "ctx.yml", "app:\n  version: '5.0'\nparameters:\n  image_repository: repo/app\n")

    without = run_cli("check", str(EXAMPLES / "generic-app"))
    with_file = run_cli("check", str(EXAMPLES / "generic-app"), "--context", str(context))

    assert "no default_version" in without.out
    assert "has no default" in without.out
    assert "no default_version" not in with_file.out
    assert "has no default" not in with_file.out
    assert with_file.out.endswith("no errors\n")
