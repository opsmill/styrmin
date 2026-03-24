"""Tests for deployment naming utilities and domain model integration."""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.domain.models import Deployment
from styrmin_backend.domain.utils import (
    generate_deployment_name,
    validate_deployment_name,
)


class TestValidateDeploymentName:
    """Tests for validate_deployment_name()."""

    def test_valid_lowercase_name(self) -> None:
        assert validate_deployment_name("my-deployment") == "my-deployment"

    def test_valid_name_with_numbers(self) -> None:
        assert validate_deployment_name("app-v2-staging-01") == "app-v2-staging-01"

    def test_valid_name_with_underscores(self) -> None:
        assert validate_deployment_name("my_deployment") == "my_deployment"

    def test_valid_name_with_hyphens_and_underscores(self) -> None:
        assert validate_deployment_name("app-v2_staging-01") == "app-v2_staging-01"

    def test_valid_single_char(self) -> None:
        assert validate_deployment_name("a") == "a"

    def test_valid_single_digit(self) -> None:
        assert validate_deployment_name("1") == "1"

    def test_valid_max_length(self) -> None:
        name = "a" * 63
        assert validate_deployment_name(name) == name

    def test_invalid_empty_string(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            validate_deployment_name("")

    def test_invalid_spaces(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_deployment_name("my deployment")

    def test_invalid_uppercase(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_deployment_name("MyDeployment")

    def test_invalid_starts_with_hyphen(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_deployment_name("-my-deployment")

    def test_invalid_starts_with_underscore(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_deployment_name("_my-deployment")

    def test_invalid_too_long(self) -> None:
        name = "a" * 64
        with pytest.raises(ValueError, match="at most 63"):
            validate_deployment_name(name)

    def test_invalid_special_characters(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_deployment_name("my.deployment")

    def test_invalid_dot(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_deployment_name("my@deployment")


class TestGenerateDeploymentName:
    """Tests for generate_deployment_name()."""

    def test_first_deployment(self) -> None:
        result = generate_deployment_name("infrahub", [])
        assert result == "infrahub-1"

    def test_sequential_numbering(self) -> None:
        result = generate_deployment_name("infrahub", ["infrahub-1"])
        assert result == "infrahub-2"

    def test_gap_handling_uses_max_plus_one(self) -> None:
        result = generate_deployment_name("infrahub", ["infrahub-1", "infrahub-3"])
        assert result == "infrahub-4"

    def test_ignores_non_matching_names(self) -> None:
        result = generate_deployment_name(
            "infrahub", ["other-app-1", "infrahub-2", "random-name"]
        )
        assert result == "infrahub-3"

    def test_driver_name_with_hyphens(self) -> None:
        result = generate_deployment_name("my-app", ["my-app-1", "my-app-2"])
        assert result == "my-app-3"

    def test_ignores_names_with_non_numeric_suffix(self) -> None:
        result = generate_deployment_name("infrahub", ["infrahub-abc", "infrahub-1"])
        assert result == "infrahub-2"

    def test_long_driver_name_truncation(self) -> None:
        long_driver = "a" * 62  # 62 chars + "-1" = 64, exceeds 63
        result = generate_deployment_name(long_driver, [])
        assert len(result) <= 63
        assert result.endswith("-1")

    def test_no_existing_names(self) -> None:
        result = generate_deployment_name("simple-app", [])
        assert result == "simple-app-1"


class TestDeploymentCreateWithName:
    """Tests for Deployment.create() with name parameter."""

    def test_create_with_valid_name(self) -> None:
        deployment = Deployment.create(
            application_version="1.0.0",
            application_driver_version_id=uuid4(),
            environment_id=uuid4(),
            name="my-deployment",
        )
        assert deployment.name == "my-deployment"

    def test_create_with_invalid_name_raises(self) -> None:
        with pytest.raises(ValueError):
            Deployment.create(
                application_version="1.0.0",
                application_driver_version_id=uuid4(),
                environment_id=uuid4(),
                name="My Deployment",
            )

    def test_create_without_name_raises(self) -> None:
        with pytest.raises(ValueError, match="must be provided"):
            Deployment.create(
                application_version="1.0.0",
                application_driver_version_id=uuid4(),
                environment_id=uuid4(),
            )

    def test_create_with_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="must be provided"):
            Deployment.create(
                application_version="1.0.0",
                application_driver_version_id=uuid4(),
                environment_id=uuid4(),
                name="",
            )

    def test_create_with_whitespace_name_raises(self) -> None:
        with pytest.raises(ValueError, match="must be provided"):
            Deployment.create(
                application_version="1.0.0",
                application_driver_version_id=uuid4(),
                environment_id=uuid4(),
                name="   ",
            )


class TestDeploymentRenameValidation:
    """Tests for deployment rename validation scenarios."""

    def test_validate_same_name_is_valid(self) -> None:
        """Same-name rename should pass validation (no-op handled at service level)."""
        assert validate_deployment_name("infrahub-1") == "infrahub-1"

    def test_validate_invalid_new_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_deployment_name("My New Name")

    def test_validate_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            validate_deployment_name("")
