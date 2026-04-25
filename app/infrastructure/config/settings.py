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

    # FRED (Federal Reserve Economic Data) — 금리·유가·환율 등 매크로 지표 조회
    fred_api_key: str = ""

    finnhub_api_key: str = ""

    # History Agent — LLM 타이틀 / causality 튜닝 파라미터 (T2-5)
    history_title_batch_size: int = 15
    history_title_concurrency: int = 10
    # NEWS 요약은 배치 내 LLM 처리 시간 선형 비례 → 작은 배치 + 병렬이 유리
    history_news_summary_batch_size: int = 5
    history_causality_pre_days: int = 14
    history_causality_post_days: int = 3
    # T2-1 Phase B: INDEX causality LLM 확장 feature flag.
    # 기본은 Phase A(규칙 기반)만 동작. True로 켜면 규칙 미매핑 케이스에 LLM 워크플로우 호출.
    index_causality_llm_enabled: bool = False

    # Data-source expansion (Tier A/B/C)
    history_holdings_concurrency: int = 3
    history_news_top_n: int = 10
    history_news_per_source_timeout_s: float = 8.0
    history_news_scrape_enabled: bool = False
    # 영문 NEWS 제목을 한국어 1문장 요약으로 교체 (비용: 기사당 1회 LLM 호출)
    history_news_korean_summary_enabled: bool = True
    history_related_assets_threshold_pct: float = 2.0
    history_related_assets_top_k: int = 100  # §13.4 B perf — |Δ%| 큰 순 상위 N건만 LLM 랭커로 전달
    history_gpr_mom_change_pct: float = 20.0
    history_gpr_top_k: int = 50  # §13.4 B perf
    history_fred_surprise_top_k: int = 100  # §13.4 B perf — FRED surprise 결과도 cap
    yfinance_retry_max_attempts: int = 3
    yfinance_retry_base_delay: float = 1.0

    # Macro timeline — 역사적 중요도 기반 매크로 이벤트 큐레이션
    macro_timeline_top_n: int = 30
    macro_importance_llm_enabled: bool = True
    macro_cache_ttl_seconds: int = 86_400

    # US market support
    enable_us_tickers: bool = False
    sec_edgar_user_agent: str = "Antelligen research@example.com"

    # Source tier weighting
    enable_source_tier_weighting: bool = False
    tier_multiplier_high: float = 1.0
    tier_multiplier_medium: float = 0.7
    tier_multiplier_medium_low: float = 0.5
    tier_multiplier_low: float = 0.3

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
