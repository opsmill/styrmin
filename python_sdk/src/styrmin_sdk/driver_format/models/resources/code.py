from pydantic import BaseModel


class Action(BaseModel):
    """The action model."""

    name: str
    function: str
    signature: str


class ActionsCode(BaseModel):
    """The actions code model."""

    actions: list[Action]
