from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mariadb_host: str = "localhost"
    mariadb_port: int = 3306
    mariadb_user: str = "testuser"
    mariadb_password: str = "test-password"
    mariadb_database: str = "testdb"
    mongodb_url: str = "mongodb://testuser:test-mongo-password@localhost:27017/testdb?authSource=admin"


settings = Settings()
