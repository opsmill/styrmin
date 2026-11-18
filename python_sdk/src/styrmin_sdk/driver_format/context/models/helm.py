from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChartInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    version: str
    values_template: str


class RepositoryInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    url: str


class HelmInfo(BaseModel):
    """Helm information.

    Holds the helm information for the application.

    Attributes:
        chart (str): The chart name.
        version (str): The chart version.
        repo (str): The chart repository.
    """

    model_config = ConfigDict(extra="forbid")

    chart: ChartInfo
    repository: RepositoryInfo
