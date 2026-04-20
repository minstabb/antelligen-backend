from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_user: str
    postgres_password: str
    postgres_host: str
    postgres_port: int
    postgres_db: str
    debug: bool = False



    naver_client_id: str
    naver_client_secret: str

    anthropic_api_key: str
    openai_api_key: str

    serp_api_key: str = ""
    youtube_api_key: str = ""

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: Optional[str] = None

    auth_password: str = ""
    session_ttl_seconds: int = 3600

    env: str = "local"

    cors_allowed_frontend_url: str = "http://localhost:3000"

    kakao_client_id: str
    kakao_redirect_uri: str

    open_dart_api_key: str = ""

    langchain_api_key: str = ""
    langchain_project: str = "disclosure-analysis"
    langchain_tracing_v2: bool = False

    analysis_api_finance_url: Optional[str] = None
    analysis_api_timeout_seconds: float = 10.0
    openai_finance_agent_model: str = "gpt-5-mini"
    openai_learning_model: str = "gpt-5-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    finance_rag_top_k: int = 3
    finance_analysis_cache_ttl_seconds: int = 3600
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "antelligen-backend"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    dart_api_key: str = ""

    fred_api_key: str = ""

    finnhub_api_key: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
