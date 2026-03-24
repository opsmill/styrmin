from typing import Annotated, Literal

from pydantic import BaseModel, Field


class GitSource(BaseModel):
    """The source of a driver loaded from a remote git repository.

    Args:
        repository (str): The repository URL.
        branch (str): The branch name.
        token (str): The token to access the repository.
    """

    type: Literal["git"] = "git"
    repository: str
    branch: str
    token: str


class LocalSource(BaseModel):
    """The source of a driver loaded from a local filesystem directory.

    Args:
        path (str): The absolute path to the driver directory.
    """

    type: Literal["local"] = "local"
    path: str


DriverSource = Annotated[GitSource | LocalSource, Field(discriminator="type")]
