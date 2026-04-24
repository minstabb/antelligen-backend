"""
Investment 워크플로우 스모크 테스트.

뉴스·유튜브 수집 → 투자 심리 지표 산출 → 분석 → 종합 전체 흐름을 실행하고
각 단계의 출력을 콘솔에 출력한다.

실행:
    python -m app.infrastructure.agent.smoke
    python -m app.infrastructure.agent.smoke "한화에어로스페이스 지금 사도 될까?"
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def _print_retrieved_data(retrieved_data: list) -> None:
    for entry in retrieved_data:
        src = entry.get("source", "?")
        status = entry.get("status", "?")
        items = entry.get("items", [])
        signal = entry.get("signal")

        print(f"\n  [{src}] status={status} | 항목={len(items)}건")

        if status == "ok" and items:
            if src == "뉴스":
                for i, item in enumerate(items[:3]):
                    title = item.get("title", "")
                    print(f"    {i + 1}. {title[:70]}")
            elif src == "유튜브":
                for i, item in enumerate(items[:3]):
                    title = item.get("title", "")
                    ch = item.get("channel_name", "")
                    comments = item.get("comments", [])
                    print(f"    {i + 1}. [{ch}] {title[:55]} (댓글 {len(comments)}건)")

        if signal:
            if src == "유튜브":
                dist = signal.get("sentiment_distribution", {})
                score = signal.get("sentiment_score", 0.0)
                print(
                    f"    ▶ 감성분포  긍정={dist.get('positive', 0):.1%} | "
                    f"중립={dist.get('neutral', 0):.1%} | "
                    f"부정={dist.get('negative', 0):.1%}"
                )
                print(f"    ▶ 감성점수  {score:+.3f}")
                print(f"    ▶ 상승키워드 {signal.get('bullish_keywords', [])}")
                print(f"    ▶ 하락키워드 {signal.get('bearish_keywords', [])}")
                print(f"    ▶ 토픽      {signal.get('topics', [])}")
                print(f"    ▶ volume   {signal.get('volume', 0)}건")
            elif src == "뉴스":
                pos = signal.get("positive_events", [])
                neg = signal.get("negative_events", [])
                kws = signal.get("keywords", [])
                print(f"    ▶ 긍정 이벤트 ({len(pos)}건)")
                for e in pos:
                    print(f"       - [{e.get('impact', '?')}] {e.get('event', '')[:60]}")
                print(f"    ▶ 부정 이벤트 ({len(neg)}건)")
                for e in neg:
                    print(f"       - [{e.get('impact', '?')}] {e.get('event', '')[:60]}")
                print(f"    ▶ 키워드    {kws}")
        elif status == "ok":
            print(f"    ▶ signal   없음 (수집 데이터 부족)")
        else:
            print(f"    ▶ error    {entry.get('error', '')}")


def _print_analysis(analysis_insights: dict) -> None:
    print(f"\n  전망:\n    {analysis_insights.get('outlook', '')}")
    print(f"\n  리스크:\n    {analysis_insights.get('risk', '')}")
    points = analysis_insights.get("investment_points", [])
    print(f"\n  투자 포인트:")
    for p in points:
        print(f"    • {p}")


async def main(query: str) -> None:
    from app.infrastructure.config.settings import get_settings
    from app.domains.investment.adapter.outbound.external.langgraph_investment_workflow import (
        LangGraphInvestmentWorkflow,
    )

    settings = get_settings()

    _section("Investment 워크플로우 스모크 테스트")
    print(f"  질의: {query!r}")

    workflow = LangGraphInvestmentWorkflow(
        api_key=settings.openai_api_key,
        serp_api_key=settings.serp_api_key,
        youtube_api_key=settings.youtube_api_key,
    )

    print("\n  워크플로우 실행 중...\n")
    final_state = await workflow.run(user_id="smoke-test", query=query)

    # ── Retrieval 결과 ──────────────────────────────────────────────────────
    _section("Retrieval 결과 + 투자 심리 지표")
    retrieved_data = final_state.get("retrieved_data", [])
    if retrieved_data:
        _print_retrieved_data(retrieved_data)
    else:
        print("  (수집 데이터 없음)")

    # ── 투자 판단 ───────────────────────────────────────────────────────────
    _section("투자 판단 (Rule-based)")
    decision = final_state.get("investment_decision", {})
    if decision:
        verdict_ko = {"buy": "매수", "hold": "보유", "sell": "매도"}
        direction_ko = {"bullish": "상승", "bearish": "하락", "neutral": "중립"}
        print(f"  verdict    : {decision.get('verdict','?').upper()} ({verdict_ko.get(decision.get('verdict',''), '')})")
        print(f"  direction  : {decision.get('direction','?')} ({direction_ko.get(decision.get('direction',''), '')})")
        print(f"  confidence : {decision.get('confidence', 0):.4f}")
        print(f"  news_score : {decision.get('news_score', 0):+.4f}")
        print(f"  sent_score : {decision.get('sentiment_score', 0):+.4f}")
        print(f"\n  rationale  : {decision.get('rationale','')}")
        print(f"\n  reasons (+):")
        for r in decision.get("reasons", {}).get("positive", []):
            print(f"    + {r}")
        print(f"  reasons (-):")
        for r in decision.get("reasons", {}).get("negative", []):
            print(f"    - {r}")
        print(f"  risk_factors:")
        for r in decision.get("risk_factors", []):
            print(f"    ⚠ {r}")
    else:
        print("  (판단 결과 없음)")

    # ── Analysis 결과 ───────────────────────────────────────────────────────
    _section("Analysis 결과")
    analysis_insights = final_state.get("analysis_insights", {})
    if analysis_insights:
        _print_analysis(analysis_insights)
    else:
        print("  (분석 결과 없음)")

    # ── 최종 응답 ───────────────────────────────────────────────────────────
    _section("최종 응답")
    print(final_state.get("final_response", "(응답 없음)"))

    # ── 실행 요약 ───────────────────────────────────────────────────────────
    _section("실행 요약")
    parsed = final_state.get("parsed_query") or {}
    print(f"  company        : {parsed.get('company')!r}")
    print(f"  intent         : {parsed.get('intent')!r}")
    print(f"  required_data  : {parsed.get('required_data')}")
    print(f"  iteration_count: {final_state.get('iteration_count', 0)}")
    print()


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "한화에어로스페이스 지금 사도 될까?"
    asyncio.run(main(query))
