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
            icon: https://docs.infrahub.app/img/infrahub-logo.svg
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
                container: infrahub-server  # optional; receives the component's env vars
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

import re
from typing import Any, Literal, Self

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ModelWrapValidatorHandler,
    PrivateAttr,
    RootModel,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from styrmin_sdk.driver_format.context.models.components import ReplicaDeclaration
from styrmin_sdk.driver_format.errors import CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL

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


_HTTP_URL: TypeAdapter[HttpUrl] = TypeAdapter(HttpUrl)


def _url_problem(value: object, *, field: str, schemes: tuple[str, ...], example: str) -> str | None:
    """Why ``value`` cannot be stored at ``field``, or None when it can."""
    try:
        url: HttpUrl | None = _HTTP_URL.validate_python(value)
    except ValidationError:
        url = None
    if url is not None and (url.username or url.password):
        # The value holds a credential, so the message does not repeat it.
        return f"{field} must not contain a username or password"
    if url is None or url.scheme not in schemes:
        kind = " or ".join(schemes)
        return f"{field} must be an absolute {kind} URL, such as {example} (found {value!r})"
    return None


def _link_problem(entry: object, field: str) -> str | None:
    """Why the ``spec.info.links`` entry at ``field`` cannot be stored, or None."""
    if not isinstance(entry, dict):
        return f"{field} must be a mapping with `link` and `url` keys"
    missing = [f"`{key}`" for key in ("link", "url") if key not in entry]
    if missing:
        noun = "key" if len(missing) == 1 else "keys"
        return f"{field} is missing the {' and '.join(missing)} {noun}"
    extra = sorted(str(key) for key in entry if key not in ("link", "url"))
    if extra:
        return f"{field} has keys other than `link` and `url`: {', '.join(extra)}"
    if not isinstance(entry["link"], str):
        return f"{field}.link must be text (found {entry['link']!r})"
    return _url_problem(
        entry["url"],
        field=f"{field}.url",
        schemes=("http", "https"),
        example="https://example.com/docs",
    )


class Info(BaseModel):
    """``spec.info``: what the driver pages show about the application.

    An invalid ``icon`` or ``links`` entry does not fail the load. It is left
    out and described in :attr:`warnings`, so files that loaded before still load.
    """

    model_config = ConfigDict(extra="forbid")

    links: list[InfoLink] | None = None
    authors: list[str] | None = None
    description: str | None = None
    license: str | None = None
    icon: HttpUrl | None = None

    _warnings: list[str] = PrivateAttr(default_factory=list)

    @model_validator(mode="wrap")
    @classmethod
    def _drop_invalid_icon_and_links(cls, data: Any, handler: ModelWrapValidatorHandler[Self]) -> Self:
        if not isinstance(data, dict):
            return handler(data)
        data = dict(data)
        warnings: list[str] = []
        if data.get("icon") is not None:
            problem = _url_problem(
                data["icon"],
                field="spec.info.icon",
                schemes=("https",),
                example="https://example.com/logo.svg",
            )
            if problem:
                warnings.append(f"{problem}. The icon was not stored.")
                del data["icon"]
        links = data.get("links")
        if links is not None and not isinstance(links, list):
            warnings.append(
                "spec.info.links must be a list of entries with `link` and `url` "
                f"keys (found {type(links).__name__}). The links were not stored."
            )
            del data["links"]
        elif links is not None:
            kept = []
            for index, entry in enumerate(links):
                problem = _link_problem(entry, f"spec.info.links[{index}]")
                if problem:
                    warnings.append(f"{problem}. The link was not stored.")
                else:
                    kept.append(entry)
            data["links"] = kept
        info = handler(data)
        info._warnings = warnings
        return info

    @property
    def warnings(self) -> list[str]:
        """Why an ``icon`` or ``links`` value of the file was not stored."""
        return list(self._warnings)


class LabelIdentifier(RootModel):
    root: dict[str, str]


class Identifier(BaseModel):
    label: LabelIdentifier


# Kubernetes container name: a DNS-1123 label.
_CONTAINER_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
_CONTAINER_NAME_MAX_LENGTH = 63


class ArbitrarySectionModel(ReplicaDeclaration):
    """One ``spec.components.<name>`` declaration.

    ``replicas`` (1 to 2147483647) and ``singleton`` come from :class:`ReplicaDeclaration`:
    they are typed on load, ``singleton: true`` with ``replicas`` above 1 fails the load, and
    each is left out of ``model_dump()`` at its default. Other keys are kept as extras.
    """

    model_config = ConfigDict(extra="allow")

    identifier: Identifier
    container: str | None = None

    @field_validator("container", mode="after")
    @classmethod
    def validate_container(cls, value: str | None) -> str | None:
        if value is not None and (len(value) > _CONTAINER_NAME_MAX_LENGTH or not _CONTAINER_NAME_RE.fullmatch(value)):
            raise ValueError(
                f"{value!r} is not a valid Kubernetes container name: use 1-63 "
                "lowercase alphanumerics or '-', starting and ending with an "
                "alphanumeric"
            )
        return value


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

    @model_validator(mode="before")
    @classmethod
    def reject_removed_container_overrides(cls, data: Any) -> Any:
        # Named here so the error links the migration guide instead of the generic extra_forbidden.
        if isinstance(data, dict) and "container_overrides" in data:
            raise PydanticCustomError(
                "removed_key",
                "spec.container_overrides was removed: Styrmin now applies container command "
                "and args overrides to each component's declared component container. Delete "
                "the block and declare components.<name>.container instead. Migration guide: "
                "{guide}",
                {"guide": CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL},
            )
        return data

    @field_validator("services", mode="after")
    @classmethod
    def validate_service_names(cls, value: list[ServiceDefinition] | None) -> list[ServiceDefinition] | None:
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
    def validate_env_var_doc_names(cls, value: list[DriverEnvVarDoc] | None) -> list[DriverEnvVarDoc] | None:
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
