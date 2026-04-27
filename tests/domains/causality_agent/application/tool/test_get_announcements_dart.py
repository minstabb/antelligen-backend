"""causality_tools.get_announcements — DART 한국 공시 통합 검증 (OKR 1 P1.5).

PR-1~3 머지 후 state["announcements"] 에 DART 공시 dict 가 흘러들어왔을 때
tool 실행 결과가 올바른지 + 문서 갱신 확인.
"""
import json

from app.domains.causality_agent.application.tool.causality_tools import (
    TOOL_DEFINITIONS,
    _exec_get_announcements,
)


def test_get_announcements_tool_documents_dart_and_korean_types():
    """tool 정의 description 에 DART + 한국 type 명시."""
    tool = next((t for t in TOOL_DEFINITIONS if t["name"] == "get_announcements"), None)
    assert tool is not None
    desc = tool["description"]
    assert "DART" in desc
    assert "EARNINGS_GUIDANCE" in desc  # 한국 잠정실적
    assert "TREASURY_STOCK" in desc
    assert "dart" in desc  # source 필드


def test_exec_get_announcements_passes_dart_records_through():
    """state 에 DART 레코드 있을 때 source/type 그대로 응답에 포함."""
    state = {
        "announcements": [
            {
                "date": "2024-03-15",
                "type": "TREASURY_STOCK",
                "title": "자기주식 취득결정",
                "source": "dart",
                "url": "https://dart.fss.or.kr/dsaf001/main.do?rceptNo=20240315000001",
                "items_str": None,
            },
            {
                "date": "2024-03-20",
                "type": "EARNINGS_GUIDANCE",
                "title": "연결재무제표 기준 영업(잠정)실적(공정공시)",
                "source": "dart",
                "url": "https://dart.fss.or.kr/dsaf001/main.do?rceptNo=20240320000002",
                "items_str": None,
            },
        ]
    }
    result_json = _exec_get_announcements(state, {})  # type: ignore[arg-type]
    payload = json.loads(result_json)

    assert payload["total_matched"] == 2
    types = {a["type"] for a in payload["announcements"]}
    assert types == {"TREASURY_STOCK", "EARNINGS_GUIDANCE"}
    assert all(a["source"] == "dart" for a in payload["announcements"])


def test_exec_get_announcements_keyword_filters_korean_title():
    """keyword 한글로 DART title 필터링."""
    state = {
        "announcements": [
            {"date": "2024-03-15", "type": "TREASURY_STOCK",
             "title": "자기주식 취득결정", "source": "dart", "url": "", "items_str": None},
            {"date": "2024-03-20", "type": "MERGER_ACQUISITION",
             "title": "회사합병결정", "source": "dart", "url": "", "items_str": None},
        ]
    }
    result_json = _exec_get_announcements(state, {"keyword": "자기주식"})  # type: ignore[arg-type]
    payload = json.loads(result_json)

    assert payload["total_matched"] == 1
    assert payload["announcements"][0]["type"] == "TREASURY_STOCK"


def test_exec_get_announcements_handles_mixed_sec_and_dart():
    """state 에 SEC + DART 혼재 시 tool 이 모두 반환 (source 차별 X)."""
    state = {
        "announcements": [
            {"date": "2024-03-15", "type": "EARNINGS_RELEASE",
             "title": "Quarterly Earnings Release", "source": "sec_edgar",
             "url": "", "items_str": "2.02"},
            {"date": "2024-03-20", "type": "TREASURY_STOCK",
             "title": "자기주식 취득결정", "source": "dart",
             "url": "", "items_str": None},
        ]
    }
    result_json = _exec_get_announcements(state, {})  # type: ignore[arg-type]
    payload = json.loads(result_json)

    assert payload["total_matched"] == 2
    sources = {a["source"] for a in payload["announcements"]}
    assert sources == {"sec_edgar", "dart"}
