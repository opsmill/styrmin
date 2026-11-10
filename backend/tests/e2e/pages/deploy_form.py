"""Page object for the deploy form (``/environments/$id/deploy``)."""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.refs import DeploymentRef
from tests.e2e.pages._dom import enter_text

if TYPE_CHECKING:
    from playwright.async_api import Page


class DeployFormPage:
    """Deploy form — driver selection, version, name, parameters, service-name overrides."""

    def __init__(self, page: Page, *, keystroke_delay_ms: int | None = None) -> None:
        self._page = page
        self._keystroke_delay_ms = keystroke_delay_ms

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
        component_replicas: dict[str, int] | None = None,
    ) -> None:
        if parameters:
            raise ScenarioActionError(
                "UiScenarioDriver does not yet support create_deployment(parameters=...); "
                "mark the scenario as api_only"
            )
        await enter_text(
            self._page.get_by_label("Deployment Name"),
            name,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )

        await self._select_driver(driver)

        # Application version input — explicitly set so we do not rely on a
        # driver-provided default.
        await enter_text(
            self._page.get_by_label("Application Version"),
            version,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )

        # One field per component of the selected driver version, labelled with its name.
        if component_replicas:
            group = self._page.get_by_role("group", name="Component replicas")
            for component, replicas in component_replicas.items():
                await enter_text(
                    group.get_by_label(f"Replicas for {component}"),
                    str(replicas),
                    keystroke_delay_ms=self._keystroke_delay_ms,
                )

        if service_name_overrides:
            group = self._page.get_by_role("group", name="Service name overrides")
            add_button = group.get_by_role("button", name="Add service name override")
            for override in service_name_overrides:
                await add_button.click()
                rows = group.locator("[data-testid=service-override-row]")
                row = rows.last
                driver_service = override.get("driverServiceName", "")
                override_name = override.get("overrideName", "")
                await enter_text(
                    row.get_by_label("Driver service"),
                    driver_service,
                    keystroke_delay_ms=self._keystroke_delay_ms,
                )
                await enter_text(
                    row.get_by_label("Override name"),
                    override_name,
                    keystroke_delay_ms=self._keystroke_delay_ms,
                )

    async def _select_driver(self, driver: str) -> None:
        # Base UI SelectTrigger has no id, so get_by_label doesn't match it —
        # target by its data-testid.
        trigger = self._page.locator("[data-testid=driver-version-select]")
        await trigger.click()
        # After the trigger opens, options render (possibly in a portal).
        # Each option renders as `"<driverName> v<driverVersionVersion>"`.
        option = self._page.get_by_role("option").filter(has_text=f"{driver} v").first
        await option.click()

    async def read_service_ingress_fields(self, *, driver: str) -> list[str]:
        """Select ``driver`` and return the driver service names that the form
        offers ingress override fields for (#598, T042). Does not submit.

        Written before the form field (T047) and run against it in T048. The form must
        be open (``goto``) first. Once a driver version is selected, the form shows a
        ``group`` named "Service ingress overrides" with a text input labelled "Ingress class for <driver service
        name>" and one labelled "FQDN suffix for <driver service name>" for each
        external service of that version, and none for an internal service.
        Raises ``ScenarioActionError`` when the group does not appear.
        """
        await self._select_driver(driver)
        group = self._page.get_by_role("group", name="Service ingress overrides")
        try:
            await group.wait_for(timeout=10_000)
        except PlaywrightTimeoutError as exc:
            raise ScenarioActionError(
                f"the deploy form shows no 'Service ingress overrides' group for {driver!r}"
            ) from exc
        labels = await group.get_by_label(
            re.compile(r"^Ingress class for ")
        ).evaluate_all(
            """els => els.map(el =>
              (el.getAttribute('aria-label') ?? el.labels?.[0]?.textContent ?? '').trim())"""
        )
        return [label.removeprefix("Ingress class for ") for label in labels]

    async def read_selected_driver_label(self) -> str:
        """Return the text currently displayed inside the driver-version trigger.

        Used to verify the trigger shows a human-readable label (e.g.
        ``simple-app v0.1.0``) rather than the raw ``applicationDriverVersionId``
        UUID after an option is selected.
        """
        trigger = self._page.locator("[data-testid=driver-version-select]")
        await trigger.wait_for()
        return (await trigger.inner_text()).strip()

    async def submit(self) -> DeploymentRef:
        await self._page.get_by_role("button", name="Deploy", exact=True).click()

        # Deterministic success signal: success card renders with a "View
        # Deployment" link whose href carries the new deployment id.
        view_link = self._page.get_by_role("link", name="View Deployment")
        # A rejected mutation renders this alert instead; surface its message.
        failure = self._page.get_by_role("alert").filter(has_text="Deployment failed")
        await view_link.or_(failure).first.wait_for()
        if await failure.is_visible():
            raise ScenarioActionError(
                f"deploy form rejected the deployment: {await failure.inner_text()}"
            )
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
