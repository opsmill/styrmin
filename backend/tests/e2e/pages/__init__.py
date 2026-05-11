"""Playwright page objects used only by :class:`UiScenarioDriver`.

Each page object wraps the locator strategy for one product area and
returns driver-neutral types (strings, dataclasses). Scenarios never
interact with these classes directly — they go through
:class:`~tests.e2e.drivers.ScenarioDriver`.
"""

from __future__ import annotations

from tests.e2e.pages.deploy_form import DeployFormPage
from tests.e2e.pages.deployment_detail import DeploymentDetailPage
from tests.e2e.pages.drivers_list import DriversListPage
from tests.e2e.pages.environments import EnvironmentDetailPage, EnvironmentsListPage
from tests.e2e.pages.login import LoginPage
from tests.e2e.pages.settings import BackupStorageLocationsListPage, SettingsPage
from tests.e2e.pages.users_admin import UsersAdminPage

__all__ = [
    "BackupStorageLocationsListPage",
    "DeployFormPage",
    "DeploymentDetailPage",
    "DriversListPage",
    "EnvironmentDetailPage",
    "EnvironmentsListPage",
    "LoginPage",
    "SettingsPage",
    "UsersAdminPage",
]
