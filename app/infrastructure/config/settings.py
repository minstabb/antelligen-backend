from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mysql_user: str
    mysql_password: str
    mysql_host: str
    mysql_port: int
    mysql_schema: str
    debug: bool = False

    naver_client_id: str
    naver_client_secret: str

    anthropic_api_key: str
    openai_api_key: str

    serp_api_key: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: Optional[str] = None

    auth_password: str
    session_ttl_seconds: int = 3600

    kakao_client_id: str
    kakao_redirect_uri: str

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
