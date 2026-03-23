import hashlib
from decimal import Decimal

from app.domains.stock.application.port.stock_data_standardizer import (
    StockDataStandardizer,
)
from app.domains.stock.domain.entity.collected_stock_data import CollectedStockData
from app.domains.stock.domain.entity.raw_collected_stock_data import (
    RawCollectedStockData,
)


class SerpStockDataStandardizer(StockDataStandardizer):
    def standardize(
        self, raw_data: RawCollectedStockData
    ) -> CollectedStockData | None:
        payload = raw_data.raw_payload
        summary = self._extract_summary(payload)
        primary_result = self._extract_primary_result(payload)

        company_summary = self._extract_company_summary(payload, primary_result)
        current_price = self._extract_current_price(payload, primary_result)
        currency = self._extract_string(
            summary.get("currency") if summary else primary_result.get("currency")
        )
        market_cap = self._extract_string(
            summary.get("market_cap") if summary else primary_result.get("market_cap")
        )
        pe_ratio = self._extract_string(
            summary.get("pe_ratio") if summary else primary_result.get("pe_ratio")
        )
        dividend_yield = self._extract_string(
            summary.get("dividend_yield")
            if summary
            else primary_result.get("dividend_yield")
        )
        reference_url = (
            self._extract_string(primary_result.get("link"))
            or self._extract_string(
                payload.get("search_metadata", {}).get("google_finance_url")
            )
            or self._extract_string(
                payload.get("search_metadata", {}).get("google_url")
            )
        )
        document_text = self._build_document_text(
            ticker=raw_data.ticker,
            stock_name=raw_data.stock_name,
            market=raw_data.market,
            company_summary=company_summary,
            current_price=current_price,
            currency=currency,
            market_cap=market_cap,
            pe_ratio=pe_ratio,
            dividend_yield=dividend_yield,
        )

        collected_types = self._determine_collected_types(
            company_summary=company_summary,
            current_price=current_price,
            market_cap=market_cap,
            pe_ratio=pe_ratio,
            dividend_yield=dividend_yield,
            document_text=document_text,
        )
        if not collected_types:
            return None

        dedup_basis = self._build_dedup_basis(
            ticker=raw_data.ticker,
            source=raw_data.source,
            document_text=document_text,
            current_price=current_price,
            currency=currency,
        )
        dedup_key = self._build_dedup_key(dedup_basis)

        return CollectedStockData(
            ticker=raw_data.ticker,
            stock_name=raw_data.stock_name,
            market=raw_data.market,
            source=raw_data.source,
            collected_at=raw_data.collected_at,
            collected_types=collected_types,
            dedup_key=dedup_key,
            dedup_basis=dedup_basis,
            company_summary=company_summary,
            current_price=current_price,
            currency=currency,
            market_cap=market_cap,
            pe_ratio=pe_ratio,
            dividend_yield=dividend_yield,
            document_text=document_text,
            reference_url=reference_url,
        )

    def _extract_summary(self, data: dict) -> dict:
        summary = data.get("summary")
        if isinstance(summary, dict):
            return summary
        return {}

    def _extract_primary_result(self, data: dict) -> dict:
        suggestions = data.get("suggestions")
        if isinstance(suggestions, list) and suggestions:
            first = suggestions[0]
            if isinstance(first, dict):
                return first
        return {}

    def _extract_company_summary(self, data: dict, primary_result: dict) -> str | None:
        summary = self._extract_summary(data)

        for key in ("description", "about", "summary", "snippet"):
            value = self._extract_string(summary.get(key))
            if value:
                return value

        for key in ("about_this_result", "knowledge_graph"):
            nested = data.get(key)
            if isinstance(nested, dict):
                for nested_key in ("description", "summary"):
                    value = self._extract_string(nested.get(nested_key))
                    if value:
                        return value

        return self._extract_string(primary_result.get("name"))

    def _extract_current_price(self, data: dict, primary_result: dict) -> str | None:
        summary = self._extract_summary(data)

        for key in ("price", "current_price", "extracted_price"):
            extracted = self._format_price(summary.get(key))
            if extracted:
                return extracted

        price_movement = data.get("price_movement")
        if isinstance(price_movement, dict):
            for key in ("price", "value"):
                extracted = self._format_price(price_movement.get(key))
                if extracted:
                    return extracted

        for key in ("price", "extracted_price"):
            extracted = self._format_price(primary_result.get(key))
            if extracted:
                return extracted

        return None

    def _format_price(self, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        if isinstance(value, (int, float, Decimal)):
            return str(value)
        return None

    def _extract_string(self, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        if isinstance(value, (int, float, Decimal)):
            return str(value)
        if isinstance(value, dict):
            for key in ("text", "value", "name"):
                nested = value.get(key)
                if nested is not None:
                    return self._extract_string(nested)
        if isinstance(value, list):
            items = [self._extract_string(item) for item in value]
            filtered_items = [item for item in items if item]
            if filtered_items:
                return ", ".join(filtered_items)
        return str(value)

    def _build_document_text(
        self,
        ticker: str,
        stock_name: str,
        market: str,
        company_summary: str | None,
        current_price: str | None,
        currency: str | None,
        market_cap: str | None,
        pe_ratio: str | None,
        dividend_yield: str | None,
    ) -> str | None:
        lines = [
            f"Ticker: {ticker}",
            f"Stock name: {stock_name}",
            f"Market: {market}",
        ]

        optional_lines = [
            ("Company summary", company_summary),
            (
                "Current price",
                self._render_price(current_price=current_price, currency=currency),
            ),
            ("Market cap", market_cap),
            ("PER", pe_ratio),
            ("Dividend yield", dividend_yield),
        ]

        for label, value in optional_lines:
            if value:
                lines.append(f"{label}: {value}")

        if len(lines) <= 3:
            return None

        return "\n".join(lines)

    def _determine_collected_types(
        self,
        company_summary: str | None,
        current_price: str | None,
        market_cap: str | None,
        pe_ratio: str | None,
        dividend_yield: str | None,
        document_text: str | None,
    ) -> list[str]:
        collected_types: list[str] = []

        if company_summary:
            collected_types.append("basic_information")

        if current_price or market_cap or pe_ratio or dividend_yield:
            collected_types.append("financial_information")

        if document_text:
            collected_types.append("document_text")

        return collected_types

    def _build_dedup_basis(
        self,
        ticker: str,
        source: str,
        document_text: str | None,
        current_price: str | None,
        currency: str | None,
    ) -> str:
        if document_text:
            normalized_text = " ".join(document_text.lower().split())
            return f"{source}|{ticker}|{normalized_text}"

        price_part = current_price or ""
        currency_part = currency or ""
        return f"{source}|{ticker}|{price_part}|{currency_part}"

    def _build_dedup_key(self, dedup_basis: str) -> str:
        return hashlib.sha256(dedup_basis.encode("utf-8")).hexdigest()

    def _render_price(
        self, current_price: str | None, currency: str | None
    ) -> str | None:
        if current_price is None:
            return None
        if currency:
            return f"{current_price} {currency}"
        return current_price
