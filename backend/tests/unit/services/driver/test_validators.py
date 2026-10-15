from pathlib import Path
from types import NoneType

import pytest

from styrmin_backend.services.driver.exceptions import ValidationError
from styrmin_backend.services.exceptions import (
    CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL,
    ENV_VARS_MIGRATION_GUIDE_URL,
    RetiredTemplateFilterError,
)
from styrmin_backend.services.driver.models.resources.actions import (
    ActionDefinition,
    HookKind,
)
from styrmin_backend.services.driver.models.structure.resource import Role
from styrmin_backend.services.driver.validators import (
    JinjaTemplateValidator,
    UserActionsValidator,
    get_validator,
)


@pytest.mark.parametrize(
    "syntax, expected_validator",
    [
        (Role.DRIVER_SPEC, NoneType),
        (Role.VALUES_TEMPLATE, JinjaTemplateValidator),
    ],
)
def test_validator_factory(syntax, expected_validator):
    """Test the validator factory."""
    validator = get_validator(syntax)
    assert isinstance(validator, expected_validator)


def test_validator_factory_with_invalid_syntax():
    """Test the validator factory with an invalid syntax."""
    with pytest.raises(ValueError):
        get_validator("invalid-syntax")


def test_jinja_template_validator():
    """Test the Jinja template validator."""
    spec_path = (
        Path(__file__).parent / "fixtures" / "local_driver_directory" / "values.j2.yml"
    )
    with open(spec_path) as f:
        data = f.read()
    validator = JinjaTemplateValidator()
    validator.validate(data=data)


def test_jinja_template_validator_with_custom_filters():
    """Test the Jinja template validator accepts templates using custom filters."""
    data = "host: {{ name | to_fqdn_label }}"
    validator = JinjaTemplateValidator()
    validator.validate(data=data)


def test_jinja_template_validator_with_split_filter():
    """Test the Jinja template validator accepts templates using the split filter."""
    data = "items: {{ names | split(',') }}"
    validator = JinjaTemplateValidator()
    validator.validate(data=data)


def test_split_filter_renders_correctly():
    """Test the split filter correctly splits a string into a list."""
    from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
        get_jinja_environment,
    )

    env = get_jinja_environment()
    template = env.from_string("{{ value | split(',') }}")
    result = template.render(value="a,b,c")
    assert result == "['a', 'b', 'c']"


def test_jinja_template_validator_with_invalid_template():
    """Test the Jinja template validator with an invalid template."""
    data = "{{ wrong "
    validator = JinjaTemplateValidator()
    with pytest.raises(ValidationError):
        validator.validate(data=data)


@pytest.mark.parametrize(
    ("filter_name", "guide"),
    [
        ("component_command", CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL),
        ("component_args", CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL),
        ("component_env_vars", ENV_VARS_MIGRATION_GUIDE_URL),
    ],
)
def test_jinja_template_validator_rejects_retired_filters(filter_name, guide):
    """A retired filter fails at driver load, not only when the operator renders."""
    data = (
        f"replicas: 1\nvalue: {{{{ components | {filter_name}('server') | tojson }}}}\n"
    )

    with pytest.raises(RetiredTemplateFilterError) as exc_info:
        JinjaTemplateValidator().validate(data=data)

    error = exc_info.value
    assert error.error_code == "RETIRED_TEMPLATE_FILTER"
    assert error.error_metadata == {"filter": filter_name, "migration_guide": guide}
    assert f"values.j2.yml line 2 calls the '{filter_name}' template filter" in str(
        error
    )
    assert guide in str(error)


@pytest.mark.parametrize(
    "data",
    [
        "{% if components | component_args('server') %}args: []{% endif %}",
        "{% filter component_command %}server{% endfilter %}",
        "{% set a = components | default({}) | component_args('server') %}",
    ],
)
def test_jinja_template_validator_rejects_retired_filters_anywhere(data):
    """Also inside a condition, a filter block or a chain, where rendering may never reach them."""
    with pytest.raises(RetiredTemplateFilterError):
        JinjaTemplateValidator().validate(data=data)


def test_jinja_template_validator_accepts_container_override_data():
    """Reading ``container_override`` as data is not a retired filter call."""
    data = "a: {{ components.server.container_override | tojson }}"
    JinjaTemplateValidator().validate(data=data)


def test_user_actions_validations():
    """Test the UserActionsValidator."""
    actions_code_path = (
        Path(__file__).parent / "fixtures" / "local_driver_directory" / "actions.py"
    )
    with open(actions_code_path) as f:
        actions_code = f.read()

    actions_definition = [
        ActionDefinition(
            name="setup-action",
            location="actions.py::setup",
            description="A setup action",
            hook=HookKind.SETUP,
            mode="core",
        ),
        ActionDefinition(
            name="update-pswd-action",
            location="actions.py::update_password",
            description="Change the password",
            hook=HookKind.UPGRADE,
            mode="post",
        ),
    ]

    validator = UserActionsValidator(actions_definition)
    validator.validate(data=actions_code)


def test_user_actions_validations_with_missing_func():
    """Test the UserActionsValidator with missing function."""
    actions_code_path = (
        Path(__file__).parent / "fixtures" / "local_driver_directory" / "actions.py"
    )
    with open(actions_code_path) as f:
        actions_code = f.read()

    actions_definition = [
        ActionDefinition(
            name="setup-action",
            location="actions.py::setup",
            description="A setup action",
            hook=HookKind.SETUP,
            mode="core",
        ),
        ActionDefinition(
            name="update-pswd-action",
            location="actions.py::update_password",
            description="Change the password",
            hook=HookKind.UPGRADE,
            mode="post",
        ),
        ActionDefinition(
            name="missing-action",
            location="actions.py::missing",
            description="Missing action",
            hook=HookKind.SETUP,
            mode="pre",
        ),
    ]

    validator = UserActionsValidator(actions_definition)
    with pytest.raises(ValidationError):
        validator.validate(data=actions_code)
