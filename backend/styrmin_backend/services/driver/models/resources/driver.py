"""Provides the validation models for the driver service.

Example:
    ```yaml
    apiVersion: "styrmin.io/v1"
    kind: ApplicationDriver
    metadata:
        name: infrahub
        version: ">=1.1.5,<=1.2.0"
    spec:
        info:
            icon: xxxx
            description: Next generation source of truth for infrastructure management
            authors: [fatih, jeremy]
            license: Apache-2.0
            links:
            - link: Homepage
                url: 'https://www.opsmill.com/'
            - link: Documentation
                url: 'https://docs.infrahub.app'
            - link: Github
                url: 'https://github.com/opsmill/infrahub'
        helm:
            main:
                location: oci://registry.opsmill.io/opsmill/chart/infrahub
                version: 2.3.*
        components:
            server:
                count: 2
                resources:
                    cpu: 4
                    memory: 16
                observabity:
                    metric:
                    enabled: true
                    port: 8000
                    path: /metrics
                identifier:
                    label:
                        infrahub/service: infrahub-server

            task-worker:
                identifier:
                    label:
                        infrahub/service: infrahub-task-worker

            neo4j:
                identifier:
                    label:
                     infrahub/service: database

            cache:
                identifier:
                    label:
                        infrahub/service: cache

            rabbitmq:
                identifier:
                    label:
                        infrahub/service: message-queue


    ```
"""

from typing import Literal, Self

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    RootModel,
    field_validator,
    model_validator,
)

from ._shared import Kind
from .actions import ActionDefinition
from .env_vars import DriverEnvVarDoc, validate_env_var_doc_names_unique
from .parameters import DriverParameterDefinition, validate_parameter_names_unique
from .services import ServiceDefinition, validate_service_names_unique


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


class HelmSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str
    version: str


class Helm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    main: HelmSettings


class InfoLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link: str
    url: HttpUrl


class Info(BaseModel):
    model_config = ConfigDict(extra="forbid")

    links: list[dict[str, str]] | None = None
    authors: list[str] | None = None
    description: str | None = None
    license: str | None = None
    icon: str | None = None


class LabelIdentifier(RootModel):
    root: dict[str, str]


class Identifier(BaseModel):
    label: LabelIdentifier


class ArbitrarySectionModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    identifier: Identifier


class Components(RootModel):
    root: dict[str, ArbitrarySectionModel]


class Specification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    supported_versions: str
    default_version: str | None = None
    info: Info
    helm: Helm
    components: Components | None = None
    parameters: list[DriverParameterDefinition] | None = None
    services: list[ServiceDefinition] | None = None
    actions: list[ActionDefinition] = Field(default_factory=list)
    env_vars: list[DriverEnvVarDoc] | None = None

    @field_validator("services", mode="after")
    @classmethod
    def validate_service_names(
        cls, value: list[ServiceDefinition] | None
    ) -> list[ServiceDefinition] | None:
        if value is not None:
            if len(value) == 0:
                raise ValueError("Services list must not be empty if provided")
            validate_service_names_unique(value)
        return value

    @field_validator("parameters", mode="after")
    @classmethod
    def validate_parameter_names(
        cls, value: list[DriverParameterDefinition] | None
    ) -> list[DriverParameterDefinition] | None:
        if value is not None:
            validate_parameter_names_unique(value)
        return value

    @field_validator("env_vars", mode="after")
    @classmethod
    def validate_env_var_doc_names(
        cls, value: list[DriverEnvVarDoc] | None
    ) -> list[DriverEnvVarDoc] | None:
        # FR-013: names within ``spec.env_vars`` MUST be unique. Mirror of
        # ``validate_parameter_names`` — uniqueness across the list.
        if value is not None:
            validate_env_var_doc_names_unique(value)
        return value

    @field_validator("supported_versions", mode="after")
    @classmethod
    def validate_supported_versions(cls, value: str) -> str:
        try:
            SpecifierSet(value)
        except InvalidSpecifier as e:
            raise ValueError(f"Invalid version string: {value}") from e
        return value

    @model_validator(mode="after")
    def validate_default_version(self) -> Self:
        if self.default_version is not None:
            specifier = SpecifierSet(self.supported_versions)
            if Version(self.default_version) not in specifier:
                msg = (
                    f"default_version '{self.default_version}' does not satisfy "
                    f"supported_versions '{self.supported_versions}'"
                )
                raise ValueError(msg)
        return self


class DriverSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_version: Literal["styrmin.io/v1"] = Field(alias="apiVersion")
    kind: Literal[Kind.ApplicationDriver]
    metadata: Metadata
    spec: Specification
