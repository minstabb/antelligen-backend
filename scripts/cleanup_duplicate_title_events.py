"""(title, event_at) 중복 경제 일정 일회성 정리 — disambiguator 활용.

흐름:
  1) economic_events 에서 (source, title, event_at) 그룹 중 size > 1 추출
  2) 각 그룹을 EconomicEvent 엔티티 리스트로 변환
  3) NewsBackedEventDisambiguator.resolve() 호출 → 살릴 후보 1건 결정
     - kept 가 그룹 내 후보면 그대로 keep, 나머지 drop
     - kept 가 새 인스턴스(canonical title 덮어씀) 면 그룹 첫 후보의 id 를 keep 하고
       title 만 UPDATE, 나머지 drop
  4) drop id 들에 대해 schedule_notifications 명시 삭제 + economic_events 삭제
     (event_impact_analyses 는 ON DELETE CASCADE 로 함께 삭제)

사용법:
  python -m scripts.cleanup_duplicate_title_events            # dry-run (기본)
  python -m scripts.cleanup_duplicate_title_events --apply    # 실제 실행
  python -m scripts.cleanup_duplicate_title_events --simple   # 키 부재/장애 시 lowest-id keep 폴백

폴백 정책 (--simple):
  - SERP/Naver/OpenAI 키가 모두 없거나 disambiguator 호출이 실패하면
    가장 작은 id 를 keep 하고 나머지를 drop. 본문 매칭은 수행하지 않음.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

from sqlalchemy import delete, select, update

from app.domains.schedule.adapter.outbound.external.news_backed_event_disambiguator import (
    NewsBackedEventDisambiguator,
)
from app.domains.schedule.domain.entity.economic_event import EconomicEvent
from app.domains.schedule.infrastructure.mapper.economic_event_mapper import (
    EconomicEventMapper,
)
from app.domains.schedule.infrastructure.orm.economic_event_orm import EconomicEventOrm
from app.domains.schedule.infrastructure.orm.schedule_notification_orm import (
    ScheduleNotificationOrm,
)
from app.infrastructure.config.settings import get_settings
from app.infrastructure.database.database import AsyncSessionLocal

logger = logging.getLogger("cleanup_duplicate_title_events")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _build_disambiguator() -> NewsBackedEventDisambiguator | None:
    """라우터의 빌더와 동일한 정책 — 키가 모두 없으면 None."""
    settings = get_settings()
    serp = None
    if getattr(settings, "serp_api_key", ""):
        from app.domains.news.adapter.outbound.external.serp_news_search_provider import (
            SerpNewsSearchProvider,
        )
        from app.domains.stock.domain.value_object.market_region import MarketRegion

        serp = SerpNewsSearchProvider(
            api_key=settings.serp_api_key, market_region=MarketRegion.US_NASDAQ
        )
    naver = None
    if getattr(settings, "naver_client_id", "") and getattr(
        settings, "naver_client_secret", ""
    ):
        from app.domains.news.adapter.outbound.external.naver_news_client import (
            NaverNewsClient,
        )

        naver = NaverNewsClient(
            client_id=settings.naver_client_id,
            client_secret=settings.naver_client_secret,
        )
    if serp is None and naver is None:
        return None
    from app.infrastructure.external.openai_responses_client import (
        get_openai_responses_client,
    )

    return NewsBackedEventDisambiguator(
        serp_provider=serp, naver_client=naver, llm_client=get_openai_responses_client()
    )


async def _load_collisions(session) -> Dict[Tuple[str, str, str], List[EconomicEventOrm]]:
    stmt = select(EconomicEventOrm).order_by(EconomicEventOrm.id.asc())
    result = await session.execute(stmt)
    rows: List[EconomicEventOrm] = list(result.scalars().all())

    groups: Dict[Tuple[str, str, str], List[EconomicEventOrm]] = defaultdict(list)
    for r in rows:
        key = (
            r.source,
            (r.title or "").strip().lower(),
            r.event_at.replace(microsecond=0).isoformat(),
        )
        groups[key].append(r)

    return {k: v for k, v in groups.items() if len(v) > 1}


def _decide_lowest_id(group: List[EconomicEventOrm]) -> Tuple[int, str | None]:
    """폴백 — id 가 가장 작은 row 를 keep 하고 나머지를 drop."""
    keep = min(group, key=lambda r: r.id)
    return keep.id, None


async def _decide_with_disambiguator(
    disambiguator: NewsBackedEventDisambiguator, group: List[EconomicEventOrm]
) -> Tuple[int, str | None]:
    """resolver 가 결정한 1건을 keep. title 이 덮어쓰기된 경우 새 title 도 반환."""
    entities = [EconomicEventMapper.to_entity(r) for r in group]
    kept = await disambiguator.resolve(entities)
    if not kept:
        return _decide_lowest_id(group)

    chosen = kept[0]
    # resolver 가 그룹 내 인스턴스를 그대로 반환 → id 일치
    for r in group:
        if r.id == chosen.id:
            return r.id, None

    # resolver 가 새 인스턴스 반환(둘 다 mismatch → canonical title 로 덮어씀)
    # 그룹 첫 row(=가장 작은 id) 를 keep 으로 삼고 title 만 UPDATE
    seed = min(group, key=lambda r: r.id)
    new_title = chosen.title if chosen.title and chosen.title != seed.title else None
    return seed.id, new_title


async def main(apply: bool, simple: bool) -> int:
    disambiguator = None if simple else _build_disambiguator()
    if disambiguator is None and not simple:
        logger.warning(
            "[cleanup] disambiguator 미구성(SERP/Naver 키 부재). --simple 폴백으로 진행"
        )
        simple = True

    async with AsyncSessionLocal() as session:
        groups = await _load_collisions(session)
        if not groups:
            logger.info("[cleanup] 중복 그룹 없음 — 정리할 것 없습니다.")
            return 0

        logger.info("[cleanup] 중복 그룹 %d건 감지", len(groups))

        keep_ids: List[int] = []
        drop_ids: List[int] = []
        title_updates: List[Tuple[int, str]] = []

        for (source, title_norm, event_at_iso), group in groups.items():
            ids = [r.id for r in group]
            if simple:
                kid, new_title = _decide_lowest_id(group)
            else:
                try:
                    kid, new_title = await _decide_with_disambiguator(
                        disambiguator, group
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[cleanup] disambiguator 실패 → lowest-id 폴백: source=%s title=%r err=%s",
                        source,
                        title_norm,
                        exc,
                    )
                    kid, new_title = _decide_lowest_id(group)

            keep_ids.append(kid)
            for i in ids:
                if i != kid:
                    drop_ids.append(i)
            if new_title:
                title_updates.append((kid, new_title))

            sample_title = group[0].title
            logger.info(
                "  group source=%s ids=%s keep=%s drop=%s%s sample=%r",
                source,
                ids,
                kid,
                [i for i in ids if i != kid],
                f" rename→{new_title!r}" if new_title else "",
                sample_title,
            )

        logger.info(
            "[cleanup] 요약: keep=%d drop=%d title_updates=%d",
            len(keep_ids),
            len(drop_ids),
            len(title_updates),
        )

        if not apply:
            logger.info(
                "[cleanup] dry-run 종료. 실제 적용하려면 --apply 를 붙여 다시 실행하세요."
            )
            return 0

        if not drop_ids and not title_updates:
            logger.info("[cleanup] 변경사항 없음.")
            return 0

        # 1) schedule_notifications orphan 정리 (FK 없음)
        if drop_ids:
            notif_del = await session.execute(
                delete(ScheduleNotificationOrm).where(
                    ScheduleNotificationOrm.event_id.in_(drop_ids)
                )
            )
            logger.info(
                "[cleanup] schedule_notifications 삭제: %d row", notif_del.rowcount or 0
            )

        # 2) economic_events 삭제 (event_impact_analyses 는 CASCADE)
        if drop_ids:
            ev_del = await session.execute(
                delete(EconomicEventOrm).where(EconomicEventOrm.id.in_(drop_ids))
            )
            logger.info(
                "[cleanup] economic_events 삭제: %d row", ev_del.rowcount or 0
            )

        # 3) title 덮어쓰기
        for kid, new_title in title_updates:
            await session.execute(
                update(EconomicEventOrm)
                .where(EconomicEventOrm.id == kid)
                .values(title=new_title)
            )
        if title_updates:
            logger.info("[cleanup] title 갱신: %d row", len(title_updates))

        await session.commit()
        logger.info("[cleanup] ✅ 커밋 완료.")
        return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="(title, event_at) 중복 경제 일정 정리")
    p.add_argument(
        "--apply",
        action="store_true",
        help="실제로 DELETE/UPDATE 실행. 미지정 시 dry-run.",
    )
    p.add_argument(
        "--simple",
        action="store_true",
        help="disambiguator 우회하고 lowest-id keep 폴백만 사용.",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(asyncio.run(main(apply=args.apply, simple=args.simple)))
