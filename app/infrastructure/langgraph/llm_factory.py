from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.infrastructure.config.settings import get_settings

_DEFAULT_MODEL = "gpt-5-mini"


@lru_cache(maxsize=8)
def get_workflow_llm(model: str = _DEFAULT_MODEL) -> ChatOpenAI:
    """워크플로우 노드에서 공유하는 ChatOpenAI 인스턴스를 반환한다."""
    settings = get_settings()
    return ChatOpenAI(
        model=model,
        api_key=settings.openai_api_key,
        temperature=0.3,
    )
