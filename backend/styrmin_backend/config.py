import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import toml
from pydantic import AliasChoices, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from styrmin_backend.db.constants import DatabaseType
from styrmin_backend.exceptions import InitializationError


class WorkflowDriver(str, Enum):
    LOCAL = "local"
    WORKER = "worker"


class UrlSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STYRMIN_URL_")

    graphql: str = "undefined"
    graphql_k8s: str = "undefined"


class KubernetesConfigMode(str, Enum):
    INCLUSTER = "incluster"
    KUBECONFIG = "kubeconfig"
    ENVVARS = "envvars"


class KubernetesSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STYRMIN_K8S_")
    default_resource_prefix: str = "styrmin"
    service_account: str = "styrmin-service-account"
    worker_image: str = "styrmin"
    cluster_domain: str = "cluster.local"

    config_mode: KubernetesConfigMode = Field(
        default=KubernetesConfigMode.INCLUSTER,
        validation_alias=AliasChoices(
            "STYRMIN_K8S_CONFIG_MODE", "KUBERNETES_CONFIG_MODE"
        ),
    )
    host: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("STYRMIN_K8S_HOST", "KUBERNETES_HOST"),
    )
    token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("STYRMIN_K8S_TOKEN", "KUBERNETES_TOKEN"),
    )
    ca_cert: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("STYRMIN_K8S_CA_CERT", "KUBERNETES_CA_CERT"),
    )

    @model_validator(mode="after")
    def validate_envvars_mode(self) -> "KubernetesSettings":
        if self.config_mode == KubernetesConfigMode.ENVVARS:
            missing = []
            if not self.host:
                missing.append("KUBERNETES_HOST")
            if not self.token:
                missing.append("KUBERNETES_TOKEN")
            if missing:
                msg = f"When KUBERNETES_CONFIG_MODE=envvars, the following environment variables are required: {', '.join(missing)}"
                raise ValueError(msg)
        return self


class RemoteAgentCodeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STYRMIN_AGENT_SOURCE_")

    token: str = Field(
        default="undefined",
        description="Token used to authenticate with the remote agent code repository.",
    )
    branch: str = "develop"
    repository: str = "https://github.com/opsmill/styrmin.git"


class WorkflowSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STYRMIN_WORKFLOW_")
    enable: bool = True
    address: str = "localhost"
    port: Optional[int] = Field(
        default=None,
        ge=1,
        le=65535,
        description="Specified if running on a non default port.",
    )
    tls_enabled: bool = Field(
        default=False, description="Indicates if TLS is enabled for the connection"
    )
    driver: WorkflowDriver = WorkflowDriver.WORKER
    default_worker_type: str = "kubernetes"
    worker_polling_interval: int = Field(
        default=2,
        ge=1,
        le=30,
        description="Specify how often the worker should poll the server for tasks (sec)",
    )

    @property
    def api_endpoint(self) -> str:
        url = "https://" if self.tls_enabled else "http://"
        url += self.address
        if self.port:
            url += f":{self.port}"
        url += "/api"
        return url


class DriverSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STYRMIN_DRIVER_")

    # TODO: Temporary token setup
    token: str = Field(
        default="undefined",
        description="Token used to authenticate with the driver",
    )

    spec_file: str = Field(default="driver.styrmin.yml")
    values_template: str = Field(default="values.j2.yml")
    actions_code_file: str = Field(default="actions.py")


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STYRMIN_DB_")

    db_type: DatabaseType = Field(default=DatabaseType.SQLITE, alias="STYRMIN_DB_TYPE")
    db_name: str = Field(default="styrmin.db", alias="STYRMIN_DB_NAME")
    # PostgreSQL connection fields
    db_host: str = Field(default="localhost", alias="STYRMIN_DB_HOST")
    db_port: int = Field(default=5432, alias="STYRMIN_DB_PORT")
    db_username: Optional[str] = Field(default=None, alias="STYRMIN_DB_USERNAME")
    db_password: Optional[str] = Field(default=None, alias="STYRMIN_DB_PASSWORD")
    db_url: Optional[str] = Field(default=None, alias="STYRMIN_DB_URL")
    echo: bool = Field(default=False, alias="STYRMIN_DB_ECHO")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STYRMIN_")
    database: DatabaseSettings = DatabaseSettings()
    workflow: WorkflowSettings = WorkflowSettings()
    kubernetes: KubernetesSettings = KubernetesSettings()
    driver: DriverSettings = DriverSettings()
    agent_code: RemoteAgentCodeSettings = RemoteAgentCodeSettings()
    url: UrlSettings = UrlSettings()  # type: ignore[call-arg]
    log_level: str = Field(
        default="INFO",
        description="Log level for the application. Can be one of DEBUG, INFO, WARNING, ERROR, CRITICAL",
    )


@dataclass
class ConfiguredSettings:  # pylint: disable=too-many-public-methods
    settings: Settings | None = None

    def initialize(self, config_file: Optional[str] = None) -> None:
        """Initialize the settings if they have not been initialized."""
        if self.initialized:
            return
        if not config_file:
            config_file_name = os.environ.get("STYRMIN_CONFIG", "styrmin.toml")
            config_file = os.path.abspath(config_file_name)
        self.settings = load(config_file)

    def initialize_and_exit(self, config_file: Optional[str] = None) -> None:
        """Initialize the settings if they have not been initialized, exit on failures."""
        if self.initialized:
            return
        if not config_file:
            config_file_name = os.environ.get("STYRMIN_CONFIG", "styrmin.toml")
            config_file = os.path.abspath(config_file_name)
        load_and_exit(config_file)

    @property
    def active_settings(self) -> Settings:
        if self.settings:
            return self.settings
        raise InitializationError

    @property
    def initialized(self) -> bool:
        return self.settings is not None

    @property
    def url(self) -> UrlSettings:
        return self.active_settings.url

    @property
    def log_level(self) -> str:
        return self.active_settings.log_level

    @property
    def database(self) -> DatabaseSettings:
        return self.active_settings.database

    @property
    def workflow(self) -> WorkflowSettings:
        return self.active_settings.workflow

    @property
    def kubernetes(self) -> KubernetesSettings:
        return self.active_settings.kubernetes

    @property
    def driver(self) -> DriverSettings:
        return self.active_settings.driver

    @property
    def agent_code(self) -> RemoteAgentCodeSettings:
        return self.active_settings.agent_code


def load(
    config_file_name: str = "styrmin.toml", config_data: Optional[dict[str, Any]] = None
) -> Settings:
    """Load configuration.

    Configuration is loaded from a config file in toml format that contains the settings,
    or from a dictionary of those settings passed in as "config_data"
    """

    if config_data:
        return Settings(**config_data)

    if os.path.exists(config_file_name):
        config_string = Path(config_file_name).read_text(encoding="utf-8")
        config_tmp = toml.loads(config_string)

        return Settings(**config_tmp)

    return Settings()


def load_and_exit(
    config_file_name: str = "styrmin.toml",
    config_data: Optional[dict[str, Any]] = None,
) -> None:
    """Calls load, but wraps it in a try except block.

    This is done to handle a ValidationError which is raised when settings are specified but invalid.
    In such cases, a message is printed to the screen indicating the settings which don't pass validation.

    Args:
        config_file_name (str, optional): [description]. Defaults to "pyproject.toml".
        config_data (dict, optional): [description]. Defaults to None.
    """
    try:
        SETTINGS.settings = load(
            config_file_name=config_file_name, config_data=config_data
        )
    except ValidationError as err:
        print(f"Configuration not valid, found {len(err.errors())} error(s)")
        for error in err.errors():
            error_locations = [str(location) for location in error["loc"]]
            print(f"  {'/'.join(error_locations)} | {error['msg']} ({error['type']})")
        sys.exit(1)


SETTINGS: ConfiguredSettings = ConfiguredSettings()
