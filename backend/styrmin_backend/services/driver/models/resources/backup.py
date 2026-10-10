from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator


class BackupKind(str, Enum):
    DISK = "disk"
    MARIADB = "mariadb"
    MONGODB = "mongodb"
    POSTGRES = "postgres"
    NEO4J = "neo4j"
    NEO4J_COMMUNITY = "neo4j-community"
    ACTION = "action"


class ComponentBackupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    kind: BackupKind | None = None
    volume: str | None = None
    volumes: list[str] | None = None
    database_name: str | None = None
    credentials_secret: str | None = None

    @field_validator("kind", mode="after")
    @classmethod
    def kind_required_when_enabled(
        cls, v: BackupKind | None, info: ValidationInfo
    ) -> BackupKind | None:
        if info.data.get("enabled") and v is None:
            raise ValueError("kind is required when backup is enabled")
        return v

    @field_validator("credentials_secret", mode="after")
    @classmethod
    def validate_credentials_secret(cls, v: Any) -> Any:
        if v is not None:
            import re

            if not re.match(r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$", v):
                raise ValueError(
                    "credentials_secret must match Kubernetes secret naming: ^[a-z0-9][a-z0-9.-]*[a-z0-9]$"
                )
        return v
