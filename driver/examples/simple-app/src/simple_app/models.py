from sqlmodel import Field, SQLModel


class AppState(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    counter: int = Field(default=0)
    version: str = Field(default="unknown")
