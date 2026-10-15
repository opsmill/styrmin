"""The combined agent entrypoint configures its services from the settings it is given."""

import pytest
from pytest_mock import MockerFixture

from styrmin_backend.config import AgentSettings, Settings, UrlSettings
from styrmin_backend.entrypoint import combined


@pytest.mark.asyncio
async def test_main_configures_the_status_reporter_from_its_settings(
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(combined.kopf, "operator", mocker.AsyncMock())
    mocker.patch.object(combined, "run_prefect_worker", mocker.AsyncMock())
    reporter = mocker.patch.object(combined, "run_status_reporter", mocker.AsyncMock())
    settings = Settings(
        url=UrlSettings(api="http://agent.test"),
        agent=AgentSettings(status_poll_interval=42),
    )

    await combined.main(settings=settings)

    reporter.assert_awaited_once_with(
        shutdown_event=combined._shutdown,
        graphql_url="http://agent.test/graphql",
        interval=42,
    )


@pytest.mark.asyncio
async def test_startup_waits_for_a_stopped_timer_to_end_its_run() -> None:
    """#446, #461: kopf removes a deleted CR's finalizer in the same cycle once its timer ends."""
    settings = combined.kopf.OperatorSettings()

    await combined.on_startup(settings=settings)

    assert (
        settings.background.instant_exit_timeout == combined.TIMER_EXIT_TIMEOUT_SECONDS
    )
