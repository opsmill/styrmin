from abc import ABC

from styrmin_backend.db.models import Action
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class ActionRepository(BaseRepository[Action], ABC):
    """Repository specific to Actions."""


class SQLModelActionRepository(BaseSQLModelRepository[Action], ActionRepository):
    """The async SQLmodel Action repository."""

    model_class = Action
