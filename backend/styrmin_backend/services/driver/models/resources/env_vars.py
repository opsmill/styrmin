"""Driver-side env-var resource model stubs.

Real ``DriverEnvVarLevel`` enum members and ``DriverEnvVarDoc`` validators land
in T047. This stub exists so that future imports such as
``from styrmin_backend.services.driver.models.resources.env_vars import ...``
resolve while the package skeleton is in place.
"""

from enum import Enum


class DriverEnvVarLevel(str, Enum):
    """Placeholder enum; concrete levels (e.g. driver/environment/deployment) land in T047."""


class DriverEnvVarDoc:
    """Placeholder model; concrete fields and validators land in T047."""
