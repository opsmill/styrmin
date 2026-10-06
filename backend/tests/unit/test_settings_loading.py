"""Settings are parsed once per process: by an entrypoint or on first access."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from styrmin_backend import config
from styrmin_backend.config import (
    AgentSettings,
    ConfiguredSettings,
    OperatorSettings,
    Settings,
    load,
)
from styrmin_backend.exceptions import InitializationError
from styrmin_backend.workflows.catalogue import PrefectCatalogue
from styrmin_backend.workflows.models import PrefectWorkPool


@pytest.fixture
def toml_file(tmp_path: Path) -> Path:
    path = tmp_path / "styrmin.toml"
    path.write_text('log_level = "DEBUG"\n', encoding="utf-8")
    return path


def test_first_access_loads_the_file_named_by_styrmin_config(
    monkeypatch: pytest.MonkeyPatch, toml_file: Path
) -> None:
    monkeypatch.setenv("STYRMIN_CONFIG", str(toml_file))
    settings = ConfiguredSettings()

    assert settings.log_level == "DEBUG"
    assert settings.config_file == str(toml_file)


def test_settings_are_parsed_only_once(toml_file: Path) -> None:
    settings = ConfiguredSettings()
    loaded = settings.initialize(str(toml_file))
    toml_file.write_text('log_level = "ERROR"\n', encoding="utf-8")

    assert settings.initialize(str(toml_file)) is loaded
    assert settings.initialize() is loaded
    assert settings.log_level == "DEBUG"


def test_loading_a_second_file_raises(tmp_path: Path, toml_file: Path) -> None:
    settings = ConfiguredSettings()
    settings.initialize(str(toml_file))

    with pytest.raises(InitializationError, match="already loaded"):
        settings.initialize(str(tmp_path / "other.toml"))


def test_sub_settings_read_env_vars_at_load_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("STYRMIN_WORKFLOW_ADDRESS", "prefect.example")
    settings = ConfiguredSettings()
    settings.initialize(str(tmp_path / "missing.toml"))

    assert settings.workflow.address == "prefect.example"


def test_operator_settings_accept_the_existing_env_var_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The STYRMIN_OPERATOR_* names take priority over the existing names.
    monkeypatch.delenv("STYRMIN_OPERATOR_DELETED_CR_TTL_HOURS", raising=False)
    monkeypatch.delenv("STYRMIN_OPERATOR_JANITOR_INTERVAL", raising=False)
    monkeypatch.setenv("STYRMIN_OPERATOR_RECONCILE_INTERVAL", "5")
    monkeypatch.setenv("DELETED_CR_TTL_HOURS", "12")
    monkeypatch.setenv("STYRMIN_JANITOR_INTERVAL", "90")

    operator = OperatorSettings()

    assert operator.reconcile_interval == 5
    assert operator.deleted_cr_ttl_hours == 12
    assert operator.janitor_interval == 90


@pytest.mark.parametrize(
    ("env_var", "settings_class"),
    [
        ("STYRMIN_AGENT_POLL_RETRY_DELAY_SECONDS", AgentSettings),
        ("STYRMIN_AGENT_POLL_INTERVAL", AgentSettings),
        ("STYRMIN_AGENT_STATUS_POLL_INTERVAL", AgentSettings),
        ("STYRMIN_OPERATOR_RECONCILE_INTERVAL", OperatorSettings),
        ("STYRMIN_JANITOR_INTERVAL", OperatorSettings),
    ],
)
def test_zero_intervals_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    settings_class: type[AgentSettings] | type[OperatorSettings],
) -> None:
    monkeypatch.setenv(env_var, "0")

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        settings_class()


def test_agent_api_token_reads_styrmin_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STYRMIN_TOKEN", "action-token")

    token = AgentSettings().api_token

    assert token is not None
    assert token.get_secret_value() == "action-token"


def test_empty_styrmin_token_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STYRMIN_TOKEN", "")

    assert AgentSettings().api_token is None


def test_agent_api_token_is_left_out_of_the_settings_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STYRMIN_TOKEN", "action-token")

    assert "api_token" not in Settings().model_dump()["agent"]


def test_agent_and_operator_settings_load_from_toml(tmp_path: Path) -> None:
    path = tmp_path / "styrmin.toml"
    path.write_text(
        "[agent]\npoll_retries = 3\n\n[operator]\ndeleted_cr_ttl_hours = 24\n",
        encoding="utf-8",
    )

    settings = load(str(path))

    assert settings.agent.poll_retries == 3
    assert settings.operator.deleted_cr_ttl_hours == 24


def test_catalogue_forwards_agent_poll_settings_to_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = AgentSettings(poll_retries=7, poll_retry_delay_seconds=3, poll_interval=4)
    monkeypatch.setattr(
        config, "SETTINGS", ConfiguredSettings(settings=Settings(agent=agent))
    )

    pool = PrefectCatalogue().get_work_pool(PrefectWorkPool.USER_WORK_POOL)

    assert pool.base_job_template is not None
    env = pool.base_job_template["variables"]["properties"]["env"]["default"]
    assert env["STYRMIN_AGENT_POLL_RETRIES"] == "7"
    assert env["STYRMIN_AGENT_POLL_RETRY_DELAY_SECONDS"] == "3"
    assert env["STYRMIN_AGENT_POLL_INTERVAL"] == "4"
