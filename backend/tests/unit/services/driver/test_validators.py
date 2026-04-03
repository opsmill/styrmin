from pathlib import Path
from types import NoneType

import pytest

from styrmin_backend.services.driver.exceptions import ValidationError
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
