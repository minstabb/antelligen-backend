"""T2-3 한글 감지 로직 테스트."""

from app.domains.history_agent.application.service.text_utils import (
    contains_hangul,
    needs_korean_summary,
)


def test_contains_hangul_true_for_korean():
    assert contains_hangul("애플 실적 발표") is True


def test_contains_hangul_false_for_english():
    assert contains_hangul("Apple reports earnings") is False


def test_contains_hangul_true_for_mixed():
    assert contains_hangul("AAPL 2025 Q3 실적") is True


def test_needs_korean_summary_false_when_mixed_korean():
    """혼용 텍스트에 한글이 섞여있으면 이미 한국어 취급 — 요약 불필요."""
    assert needs_korean_summary("AAPL 2025 Q3 실적 발표") is False


def test_needs_korean_summary_false_for_short_english():
    assert needs_korean_summary("Apple reports Q3 earnings.") is False


def test_needs_korean_summary_true_for_long_pure_english():
    text = "Apple Inc. announced record revenue in its third fiscal quarter. " * 5
    assert needs_korean_summary(text) is True


def test_needs_korean_summary_false_for_empty():
    assert needs_korean_summary("") is False


def test_needs_korean_summary_false_when_only_hangul():
    assert needs_korean_summary("한글만 포함된 짧은 텍스트") is False
