"""Page object for the deploy form (``/environments/$id/deploy``)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.refs import DeploymentRef

if TYPE_CHECKING:
    from playwright.async_api import Page


class DeployFormPage:
    """Deploy form — driver selection, version, name, parameters, service-name overrides."""

    def __init__(self, page: Page) -> None:
        self._page = page

    async def goto(self, *, environment_id: str) -> None:
        await self._page.goto(f"/environments/{environment_id}/deploy")
        # Form renders after the drivers list query resolves; wait for the
        # submit button to appear as a stable readiness anchor.
        await self._page.get_by_role("button", name="Deploy", exact=True).wait_for()

    async def fill(
        self,
        *,
        driver: str,
        version: str,
        name: str,
        parameters: dict[str, Any] | None = None,
        service_name_overrides: list[dict[str, str]] | None = None,
    ) -> None:
        if parameters:
            # The deploy form renders driver-version-specific parameter widgets
            # (checkbox / select / integer / text — see DynamicParameterField).
            # Mapping a scenario's ``parameters`` dict onto those widgets is
            # non-trivial because Select widgets don't expose the parameter
            # name as an input id; implement per-kind mapping when the first
            # parameter-sensitive scenario lands.
            raise ScenarioActionError(
                "UiScenarioDriver does not yet support create_deployment(parameters=...); "
                "implement dynamic-parameter fill or mark the scenario as api_only"
            )
        await self._page.get_by_label("Deployment Name").fill(name)

        # Driver-version combobox: the Label's htmlFor="driverVersion" points
        # to no matching element (the Radix SelectTrigger has no id), so
        # get_by_label doesn't find the trigger. Target the only combobox
        # on the deploy form by its placeholder text.
        trigger = self._page.get_by_role("combobox").filter(
            has_text="Select a driver version"
        )
        await trigger.click()
        # After the trigger opens, options render (possibly in a portal).
        # Each option renders as `"<driverName> v<driverVersionVersion>"`.
        option = self._page.get_by_role("option").filter(has_text=f"{driver} v").first
        await option.click()

        # Application version input — explicitly set so we do not rely on a
        # driver-provided default.
        await self._page.get_by_label("Application Version").fill(version)

        if service_name_overrides:
            group = self._page.get_by_role("group", name="Service name overrides")
            add_button = group.get_by_role("button", name="Add service name override")
            for override in service_name_overrides:
                await add_button.click()
                rows = group.locator("[data-testid=service-override-row]")
                row = rows.last
                driver_service = override.get("driverServiceName", "")
                override_name = override.get("overrideName", "")
                await row.get_by_label("Driver service").fill(driver_service)
                await row.get_by_label("Override name").fill(override_name)

    async def submit(self) -> DeploymentRef:
        await self._page.get_by_role("button", name="Deploy", exact=True).click()

        # Deterministic success signal: success card renders with a "View
        # Deployment" link whose href carries the new deployment id.
        view_link = self._page.get_by_role("link", name="View Deployment")
        await view_link.wait_for()
        href = await view_link.get_attribute("href")
        if not href:
            raise ScenarioActionError(
                "deploy form success page rendered without a View Deployment link"
            )
        # href shape: /environments/<envId>/deployments/<deploymentId>
        parts = href.rstrip("/").rsplit("/", 1)
        if len(parts) != 2 or not parts[1]:
            raise ScenarioActionError(
                f"could not extract deployment id from link href: {href!r}"
            )
        deployment_id = parts[1]
        return DeploymentRef(
            id=deployment_id,
            status="pending",
            application_version=None,
            instance_id=None,
        )
