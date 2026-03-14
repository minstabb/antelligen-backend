from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mysql_user: str
    mysql_password: str
    mysql_host: str
    mysql_port: int
    mysql_schema: str
    debug: bool = False

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
