import random

from app.domains.agent.application.port.sub_agent_provider import SubAgentProvider
from app.domains.agent.application.response.investment_signal_response import (
    InvestmentSignalResponse,
)
from app.domains.agent.application.response.sub_agent_response import SubAgentResponse

MOCK_STOCK_DATA = {
    "005930": {
        "ticker": "005930",
        "stock_name": "삼성전자",
        "market": "KOSPI",
        "current_price": 72000,
        "change_rate": -1.23,
    },
    "000660": {
        "ticker": "000660",
        "stock_name": "SK하이닉스",
        "market": "KOSPI",
        "current_price": 185000,
        "change_rate": 2.45,
    },
    "005380": {
        "ticker": "005380",
        "stock_name": "현대자동차",
        "market": "KOSPI",
        "current_price": 248000,
        "change_rate": 0.81,
    },
    "035420": {
        "ticker": "035420",
        "stock_name": "네이버",
        "market": "KOSPI",
        "current_price": 210000,
        "change_rate": -0.47,
    },
    "035720": {
        "ticker": "035720",
        "stock_name": "카카오",
        "market": "KOSPI",
        "current_price": 42000,
        "change_rate": 1.20,
    },
}

MOCK_NEWS_SIGNALS: dict[str, dict] = {
    "005930": {
        "agent_name": "news",
        "ticker": "005930",
        "signal": "bullish",
        "confidence": 0.82,
        "summary": "삼성전자 AI 반도체 투자 확대 발표로 긍정적 전망",
        "key_points": [
            "AI 반도체 설비 투자 3조원 추가 확정",
            "HBM4 양산 일정 앞당김",
            "주요 외국계 증권사 목표가 상향",
        ],
    },
    "000660": {
        "agent_name": "news",
        "ticker": "000660",
        "signal": "bullish",
        "confidence": 0.78,
        "summary": "SK하이닉스 HBM4 양산 본격화로 실적 개선 기대",
        "key_points": [
            "HBM4 양산 라인 가동 시작",
            "엔비디아 공급 계약 확대",
        ],
    },
}

MOCK_FINANCE_SIGNALS: dict[str, dict] = {
    "005930": {
        "agent_name": "finance",
        "ticker": "005930",
        "signal": "neutral",
        "confidence": 0.55,
        "summary": "매출 성장세 유지되나 영업이익률 소폭 하락",
        "key_points": [
            "2025-Q4 매출 258조 1600억 (전년 대비 +12%)",
            "영업이익률 2.5%로 전분기 대비 하락",
            "반도체 부문 회복세 지속",
        ],
    },
    "000660": {
        "agent_name": "finance",
        "ticker": "000660",
        "signal": "bullish",
        "confidence": 0.88,
        "summary": "HBM 매출 급증으로 역대 최대 영업이익 달성",
        "key_points": [
            "2025-Q4 영업이익 23조 4600억 (역대 최대)",
            "HBM 매출 비중 50% 돌파",
            "DRAM ASP 상승 지속",
        ],
    },
}

MOCK_DISCLOSURE_SIGNALS: dict[str, dict] = {
    "005930": {
        "agent_name": "disclosure",
        "ticker": "005930",
        "signal": "bearish",
        "confidence": 0.71,
        "summary": "자기주식 처분 공시로 단기 수급 부담",
        "key_points": [
            "자기주식 500만주 처분 결정",
            "처분 예정 기간 3개월",
            "단기 주가 희석 우려",
        ],
    },
}

DEFAULT_TICKER = "005930"
COMPANY_NAME_TO_TICKER = {
    "samsung electronics": "005930",
    "samsung": "005930",
    "sk hynix": "000660",
    "hynix": "000660",
    "hyundai motor": "005380",
    "naver": "035420",
    "kakao": "035720",
}


class MockSubAgentProvider(SubAgentProvider):
    def resolve_ticker(self, ticker: str | None, company_name: str | None) -> str | None:
        if ticker:
            return ticker

        if company_name is None:
            return None

        return COMPANY_NAME_TO_TICKER.get(company_name.strip().lower())

    def call(self, agent_name: str, ticker: str | None, query: str) -> SubAgentResponse:
        target_ticker = ticker or DEFAULT_TICKER
        execution_time_ms = random.randint(100, 800)

        handler = {
            "stock": self._stock,
            "news": self._news,
            "finance": self._finance,
            "disclosure": self._disclosure,
        }.get(agent_name)

        if handler is None:
            return SubAgentResponse.error(
                agent_name,
                f"알 수 없는 에이전트: {agent_name}",
                execution_time_ms,
            )

        return handler(target_ticker, execution_time_ms)

    def _stock(self, ticker: str, ms: int) -> SubAgentResponse:
        data = MOCK_STOCK_DATA.get(ticker)
        if data:
            return SubAgentResponse.success("stock", data, ms)
        return SubAgentResponse.no_data("stock", ms)

    def _news(self, ticker: str, ms: int) -> SubAgentResponse:
        signal_data = MOCK_NEWS_SIGNALS.get(ticker)
        if signal_data:
            signal = InvestmentSignalResponse(**signal_data)
            return SubAgentResponse.success_with_signal(signal, {"ticker": ticker}, ms)
        return SubAgentResponse.no_data("news", ms)

    def _finance(self, ticker: str, ms: int) -> SubAgentResponse:
        signal_data = MOCK_FINANCE_SIGNALS.get(ticker)
        if signal_data:
            signal = InvestmentSignalResponse(**signal_data)
            data = {
                "ticker": ticker,
                "stock_name": MOCK_STOCK_DATA.get(ticker, {}).get("stock_name"),
            }
            return SubAgentResponse.success_with_signal(signal, data, ms)
        return SubAgentResponse.no_data("finance", ms)

    def _disclosure(self, ticker: str, ms: int) -> SubAgentResponse:
        signal_data = MOCK_DISCLOSURE_SIGNALS.get(ticker)
        if signal_data:
            signal = InvestmentSignalResponse(**signal_data)
            return SubAgentResponse.success_with_signal(signal, {"ticker": ticker}, ms)
        return SubAgentResponse.no_data("disclosure", ms)
