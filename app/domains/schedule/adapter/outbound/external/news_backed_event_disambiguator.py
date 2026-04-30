"""뉴스 검색 + LLM 으로 (title, event_at) 충돌 그룹을 해소하는 어댑터.

흐름:
  1) 영문 SERP 와 한글 Naver 를 병행 호출해 발표일 전후 기사 수집
  2) snippet/description 을 LLM 에 던져 '정식 release 명칭' 1개를 추출
  3) 충돌 그룹의 각 후보 (title + description) 와 명칭의 토큰 자카드로 매칭
  4) 임계치 이상의 후보가 있으면 그 후보 1건만 반환 (가장 점수 높은 1건)
  5) 모두 임계치 미만이면 첫 번째 후보의 메타를 차용해 title 만 정식 명칭으로
     덮어쓴 1건을 반환 (검색 데이터 반영).
"""

import asyncio
import json
import logging
import re
from typing import List, Optional, Protocol

from app.domains.schedule.application.port.out.event_disambiguation_port import (
    EventDisambiguationPort,
)
from app.domains.schedule.domain.entity.economic_event import EconomicEvent
from app.infrastructure.external.openai_responses_client import OpenAIResponsesClient

logger = logging.getLogger(__name__)


class _SerpSearchLike(Protocol):
    async def search(self, keyword: str, page: int, page_size: int): ...


class _NaverSearchLike(Protocol):
    async def search(self, keyword: str, display: int = 100, start: int = 1): ...


_LLM_INSTRUCTIONS = (
    "You are a financial calendar disambiguator. "
    "Given news snippets that all describe a single US/global economic release, "
    "identify the OFFICIAL release name as it appears on the source agency "
    "(BLS, BEA, Census, Federal Reserve, Chicago Fed, etc.). "
    "Return STRICT JSON with keys: canonical_name (string), alternative_names (array of strings). "
    "Do not include any markdown or commentary."
)

_LLM_SCHEMA = {
    "type": "json_schema",
    "name": "release_disambiguation",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["canonical_name", "alternative_names"],
        "properties": {
            "canonical_name": {"type": "string"},
            "alternative_names": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    },
    "strict": True,
}

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "by",
    "release", "report", "summary", "data", "us", "u.s",
}
_MATCH_THRESHOLD = 0.34  # Jaccard 유사도 임계


class NewsBackedEventDisambiguator(EventDisambiguationPort):
    def __init__(
        self,
        serp_provider: Optional[_SerpSearchLike],
        naver_client: Optional[_NaverSearchLike],
        llm_client: OpenAIResponsesClient,
        max_articles_per_source: int = 5,
    ):
        self._serp = serp_provider
        self._naver = naver_client
        self._llm = llm_client
        self._max = max_articles_per_source

    async def resolve(
        self, conflicting_events: List[EconomicEvent]
    ) -> List[EconomicEvent]:
        if len(conflicting_events) < 2:
            return list(conflicting_events)

        seed = conflicting_events[0]
        date_str = seed.event_at.date().isoformat()
        en_query = f"{seed.title} release {date_str}"
        ko_query = f"{seed.title} {date_str}"

        snippets = await self._collect_snippets(en_query, ko_query)
        if not snippets:
            print(
                f"[schedule.disambig] 뉴스 결과 없음 → 첫 후보 유지 "
                f"title={seed.title!r} group={len(conflicting_events)}"
            )
            return [seed]

        canonical, alternates = await self._extract_canonical_name(seed.title, snippets)
        if not canonical:
            print(f"[schedule.disambig] 명칭 추출 실패 → 첫 후보 유지 title={seed.title!r}")
            return [seed]

        print(
            f"[schedule.disambig] canonical={canonical!r} "
            f"alts={alternates[:3]} group_size={len(conflicting_events)}"
        )

        scored = []
        for ev in conflicting_events:
            score = self._best_match_score(ev, canonical, alternates)
            scored.append((score, ev))
        scored.sort(key=lambda x: x[0], reverse=True)

        top_score, top_event = scored[0]
        if top_score >= _MATCH_THRESHOLD:
            print(
                f"[schedule.disambig] ✓ 매칭 성공 score={top_score:.2f} "
                f"chosen_title={top_event.title!r} drop={len(conflicting_events) - 1}"
            )
            return [top_event]

        # 둘 다 mismatch — 검색 데이터 반영: 첫 후보의 메타에 title 만 canonical 로 덮어씀
        print(
            f"[schedule.disambig] ✗ 모두 임계 미만(top={top_score:.2f}) "
            f"→ 뉴스 명칭으로 덮어씀: {canonical!r}"
        )
        replacement = EconomicEvent(
            source=seed.source,
            source_event_id=seed.source_event_id,
            title=canonical,
            country=seed.country,
            event_at=seed.event_at,
            importance=seed.importance,
            description=seed.description,
            reference_url=seed.reference_url,
            id=seed.id,
        )
        return [replacement]

    async def _collect_snippets(self, en_query: str, ko_query: str) -> List[str]:
        tasks = []
        if self._serp is not None:
            tasks.append(self._safe_serp(en_query))
        if self._naver is not None:
            tasks.append(self._safe_naver(ko_query))
        if not tasks:
            return []
        results = await asyncio.gather(*tasks, return_exceptions=False)
        snippets: List[str] = []
        for batch in results:
            snippets.extend(batch)
        return snippets

    async def _safe_serp(self, query: str) -> List[str]:
        try:
            result = await self._serp.search(keyword=query, page=1, page_size=self._max)
            articles = getattr(result, "articles", []) or []
            out: List[str] = []
            for art in articles[: self._max]:
                title = getattr(art, "title", "") or ""
                snippet = getattr(art, "snippet", "") or ""
                line = f"{title} — {snippet}".strip(" —")
                if line:
                    out.append(line)
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("[schedule.disambig] SERP 실패: %s", exc)
            return []

    async def _safe_naver(self, query: str) -> List[str]:
        try:
            items = await self._naver.search(keyword=query, display=self._max, start=1)
            out: List[str] = []
            for it in items[: self._max]:
                title = getattr(it, "title", "") or ""
                desc = getattr(it, "description", "") or ""
                line = f"{title} — {desc}".strip(" —")
                if line:
                    out.append(line)
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("[schedule.disambig] Naver 실패: %s", exc)
            return []

    async def _extract_canonical_name(
        self, fallback_title: str, snippets: List[str]
    ) -> tuple[str, List[str]]:
        joined = "\n".join(f"- {s}" for s in snippets[:12])
        input_text = (
            f"Reported title (may be ambiguous): {fallback_title}\n\n"
            f"News snippets:\n{joined}\n\n"
            "Return the official agency-published release name."
        )
        try:
            result = await self._llm.create(
                instructions=_LLM_INSTRUCTIONS,
                input_text=input_text,
                text_format=_LLM_SCHEMA,
                max_output_tokens=300,
                reasoning={"effort": "low"},
                timeout=30.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[schedule.disambig] LLM 호출 실패: %s", exc)
            return "", []

        raw = (result.output_text or "").strip()
        if not raw:
            return "", []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return "", []
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                return "", []

        canonical = (payload.get("canonical_name") or "").strip()
        alts = [a.strip() for a in (payload.get("alternative_names") or []) if a]
        return canonical, alts

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            t.lower()
            for t in _TOKEN_RE.findall(text or "")
            if t.lower() not in _STOPWORDS and len(t) > 1
        }

    def _jaccard(self, a: str, b: str) -> float:
        ta = self._tokens(a)
        tb = self._tokens(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    def _best_match_score(
        self, event: EconomicEvent, canonical: str, alternates: List[str]
    ) -> float:
        candidate_text = f"{event.title} {event.description or ''}"
        scores = [self._jaccard(candidate_text, canonical)]
        for alt in alternates:
            scores.append(self._jaccard(candidate_text, alt))
        return max(scores) if scores else 0.0
