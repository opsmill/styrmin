from enum import Enum


class DatabaseType(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"
