"""Config Class."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Main Settings Class for the project."""

    model_config = SettingsConfigDict(env_prefix="STYRMIN_", populate_by_name=True, extra="allow")
    server_address: str = Field(default="http://localhost:8000", validation_alias="styrmin_address")
    timeout: float = Field(default=30.0)
    additional_headers: dict = Field(default={})

    @field_validator("server_address")
    @classmethod
    def cleanup_server_address(cls, v: str) -> str:
        return v.rstrip("/")


SETTINGS = Settings()
