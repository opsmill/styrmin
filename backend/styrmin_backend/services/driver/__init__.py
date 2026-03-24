from dataclasses import dataclass

from styrmin_backend.services.driver.models.resources.actions import ActionsSpec
from styrmin_backend.services.driver.models.resources.driver import DriverSpec
from styrmin_backend.services.driver.models.structure.source import DriverSource


@dataclass
class ApplicationDriver:
    source: DriverSource
    driver_spec: DriverSpec
    values_template: str
    actions_spec: ActionsSpec | None = None
