import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import toml
from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from styrmin_backend.db.constants import DatabaseType
from styrmin_backend.exceptions import InitializationError

#: Carries a reconcile's API token into the jobs it starts (ADR-059). The SDK
#: reads the same variable, so a driver action using it is authenticated too.
API_TOKEN_ENV = "STYRMIN_TOKEN"


class WorkflowDriver(str, Enum):
    LOCAL = "local"
    WORKER = "worker"


class UrlSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STYRMIN_URL_")

    api: str = "http://localhost:8000"
    api_k8s: str = "http://localhost:8000"

    @property
    def graphql(self) -> str:
        return f"{self.api}/graphql"

    @property
    def graphql_k8s(self) -> str:
        return f"{self.api_k8s}/graphql"


class KubernetesConfigMode(str, Enum):
    INCLUSTER = "incluster"
    KUBECONFIG = "kubeconfig"
    ENVVARS = "envvars"


class KubernetesSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STYRMIN_K8S_", populate_by_name=True)
    default_resource_prefix: str = "styrmin"
    service_account: str = "styrmin-service-account"
    worker_image: str = "registry.opsmill.io/opsmill/styrmin"
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
    kubeconfig: Optional[str] = Field(
        default=None,
        validation_alias="KUBECONFIG",
        description="Kubeconfig path(s) used when config_mode is kubeconfig.",
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
    model_config = SettingsConfigDict(env_prefix="STYRMIN_DB_", populate_by_name=True)

    db_type: DatabaseType = Field(default=DatabaseType.SQLITE, alias="STYRMIN_DB_TYPE")
    db_name: str = Field(default="styrmin.db", alias="STYRMIN_DB_NAME")
    # PostgreSQL connection fields
    db_host: str = Field(default="localhost", alias="STYRMIN_DB_HOST")
    db_port: int = Field(default=5432, alias="STYRMIN_DB_PORT")
    db_username: Optional[str] = Field(default=None, alias="STYRMIN_DB_USERNAME")
    db_password: Optional[str] = Field(default=None, alias="STYRMIN_DB_PASSWORD")
    db_url: Optional[str] = Field(default=None, alias="STYRMIN_DB_URL")
    echo: bool = Field(default=False, alias="STYRMIN_DB_ECHO")


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STYRMIN_AGENT_", populate_by_name=True
    )

    poll_retries: int = Field(default=60, ge=0)
    poll_retry_delay_seconds: int = Field(default=10, ge=1)
    poll_interval: int = Field(default=10, ge=1)
    status_poll_interval: int = Field(default=5, ge=1)
    api_token: Optional[SecretStr] = Field(
        default=None,
        validation_alias=API_TOKEN_ENV,
        exclude=True,
        description="Token of the running reconcile, set by Styrmin on its jobs (ADR-059).",
    )

    @field_validator("api_token", mode="before")
    @classmethod
    def empty_api_token_is_unset(cls, value: Any) -> Any:
        return value or None


class OperatorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STYRMIN_OPERATOR_", populate_by_name=True
    )

    reconcile_interval: int = Field(default=60, ge=1)
    # Below FluxCD's 5-minute HelmRelease timeout, whose rollback removes the failing pods.
    # The timer waits for this timeout when its next run would come after it.
    deployment_ready_timeout: int = Field(default=270, ge=1)
    peering_name: str = "styrmin-operator"
    peering_priority: int = 100
    deleted_cr_ttl_hours: int = Field(
        default=6,
        ge=0,
        validation_alias=AliasChoices(
            "STYRMIN_OPERATOR_DELETED_CR_TTL_HOURS", "DELETED_CR_TTL_HOURS"
        ),
    )
    janitor_interval: int = Field(
        default=1800,
        ge=1,
        validation_alias=AliasChoices(
            "STYRMIN_OPERATOR_JANITOR_INTERVAL", "STYRMIN_JANITOR_INTERVAL"
        ),
    )


DEFAULT_TELEMETRY_ENDPOINT = (
    "https://telemetry-endpoints.cloudflare-096.workers.dev/styrmin"
)


class TelemetrySettings(BaseSettings):
    """Daily anonymous report (spec 020). See the configuration contract."""

    model_config = SettingsConfigDict(env_prefix="STYRMIN_TELEMETRY_")

    enabled: bool = True
    endpoint: str = DEFAULT_TELEMETRY_ENDPOINT
    do_not_track: str | None = Field(default=None, validation_alias="DO_NOT_TRACK")

    @field_validator("endpoint", mode="before")
    @classmethod
    def blank_endpoint_is_default(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return DEFAULT_TELEMETRY_ENDPOINT
        return value

    def disabled_by(self) -> str | None:
        """Name the setting that turns telemetry off, or None when it is on."""
        if not self.enabled:
            return "STYRMIN_TELEMETRY_ENABLED=false"
        if self.do_not_track == "1":
            return "DO_NOT_TRACK=1"
        return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STYRMIN_", populate_by_name=True)
    # default_factory reads the sub-settings' env vars at load time, not import time.
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    kubernetes: KubernetesSettings = Field(default_factory=KubernetesSettings)
    driver: DriverSettings = Field(default_factory=DriverSettings)
    agent_code: RemoteAgentCodeSettings = Field(default_factory=RemoteAgentCodeSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    operator: OperatorSettings = Field(default_factory=OperatorSettings)
    url: UrlSettings = Field(default_factory=UrlSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)
    log_level: str = Field(
        default="INFO",
        description="Log level for the application. Can be one of DEBUG, INFO, WARNING, ERROR, CRITICAL",
    )
    admin_username: str = Field(
        default="admin",
        description="Username seeded by the bootstrap routine on first boot. See ADR-016.",
    )
    admin_password: Optional[str] = Field(
        default=None,
        description=(
            "Password seeded by the bootstrap routine on first boot. When unset, "
            "a random password is generated and logged once at WARN level. See ADR-016."
        ),
    )
    session_cookie_secure: bool = Field(
        default=True,
        alias="STYRMIN_SESSION_COOKIE_SECURE",
        description=(
            "Whether to set the Secure attribute on the session cookie. "
            "Defaults to True; production must serve over HTTPS. Set to False "
            "only for local HTTP demos — browsers drop Secure cookies on "
            "non-HTTPS, non-localhost origins."
        ),
    )


# Left out of `styrmin config show`: a value in styrmin.toml overrides its STYRMIN_* env var,
# so a saved output would pin these credentials over the environment.
SECRET_FIELDS: dict[str, bool | set[str]] = {
    "admin_password": True,
    "database": {"db_password", "db_url"},
    "kubernetes": {"token"},
    "driver": {"token"},
    "agent_code": {"token"},
}


@dataclass
class ConfiguredSettings:  # pylint: disable=too-many-public-methods
    """Process-wide settings, parsed once: by an entrypoint or on first access."""

    settings: Settings | None = None
    config_file: str | None = None

    def initialize(self, config_file: Optional[str] = None) -> Settings:
        """Load the settings unless they are already loaded, and return them.

        Raises InitializationError when asked for another file than the one already loaded.
        """
        path = os.path.abspath(
            config_file or os.environ.get("STYRMIN_CONFIG", "styrmin.toml")
        )
        if self.settings is None:
            self.settings = load(path)
            self.config_file = path
        elif config_file and path != self.config_file:
            msg = f"Settings already loaded from {self.config_file}, cannot load {path}"
            raise InitializationError(msg)
        return self.settings

    def initialize_and_exit(self, config_file: Optional[str] = None) -> Settings:
        """Same as initialize(), but print validation errors and exit."""
        try:
            return self.initialize(config_file)
        except ValidationError as err:
            print(f"Configuration not valid, found {len(err.errors())} error(s)")
            for error in err.errors():
                error_locations = [str(location) for location in error["loc"]]
                print(
                    f"  {'/'.join(error_locations)} | {error['msg']} ({error['type']})"
                )
            sys.exit(1)

    @property
    def active_settings(self) -> Settings:
        if self.settings is None:
            return self.initialize()
        return self.settings

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

    @property
    def agent(self) -> AgentSettings:
        return self.active_settings.agent

    @property
    def operator(self) -> OperatorSettings:
        return self.active_settings.operator

    @property
    def telemetry(self) -> TelemetrySettings:
        return self.active_settings.telemetry


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


SETTINGS: ConfiguredSettings = ConfiguredSettings()
