"""타임라인 이벤트의 텍스트 처리 유틸리티."""

import re

_HANGUL_RE = re.compile(r"[\uAC00-\uD7A3]")
_MIN_LEN_FOR_ENGLISH_SUMMARIZATION = 200
_MAX_LEN_FOR_KOREAN_SKIP = 500


def contains_hangul(text: str) -> bool:
    return bool(_HANGUL_RE.search(text))


def needs_korean_summary(text: str) -> bool:
    """영문 공시 본문을 한국어 요약으로 대체할 가치가 있는지 판정.

    규칙:
    - 한글이 단 하나라도 포함되어 있고 길이가 500자 미만이면 요약 불필요 (이미 한국어 혼재).
    - 순수 비한글(ASCII 등)이면서 길이가 최소 200자 이상일 때만 요약한다.
      짧은 영문 헤드라인(< 200자)은 그대로 노출해 LLM 비용·오역 리스크를 피한다.
    """
    if not text:
        return False
    if contains_hangul(text):
        return False
    return len(text) >= _MIN_LEN_FOR_ENGLISH_SUMMARIZATION


def needs_news_korean_translation(text: str) -> bool:
    """NEWS 제목을 한국어로 번역할 가치가 있는지 판정.

    공시 본문과 달리 뉴스 제목은 보통 10~30단어의 짧은 영문이라 길이 임계를 두지 않는다.
    - 한글이 포함되어 있으면 스킵 (이미 한국어/혼재 제목).
    - 영문·비한글이면 최소 10글자 이상일 때 요약 대상 (한두 단어 태그성 제목은 스킵).
    """
    if not text:
        return False
    if contains_hangul(text):
        return False
    return len(text.strip()) >= 10
