"""T2-1 Phase B INDEX causality LLM 품질 평가.

평가 실행은 --eval 플래그가 있을 때만 실제 LLM을 호출한다. 그 외에는 fixture
로딩만 검증해 CI 시간을 낭비하지 않는다.

Feature flag `settings.index_causality_llm_enabled`는 이 eval이 fixtures/ 30건
기준을 통과한 뒤에만 True로 전환해야 한다.
"""

import datetime
import json
from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixtures():
    return sorted(_FIXTURES_DIR.glob("sample_*.json"))


def test_fixtures_parseable():
    """모든 샘플이 필수 키를 가진 JSON 이어야 한다."""
    samples = _load_fixtures()
    assert samples, "golden-set fixtures가 비어있다 — README 참조"
    for path in samples:
        data = json.loads(path.read_text())
        for key in ("index_ticker", "event", "context_macro", "expected_keywords"):
            assert key in data, f"{path.name}: missing {key}"
        datetime.date.fromisoformat(data["event"]["date"])


@pytest.mark.skip(reason="--eval 플래그 전용 — 실 LLM 호출, 비용 발생")
async def test_phase_b_accuracy():
    """30건 기준 정확성 70% + 금칙 0건 + 비용/지연 상한 충족.

    TODO: --eval 옵션 파싱을 conftest에 추가한 뒤 활성화.
    """
    pass
