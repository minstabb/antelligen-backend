"""한국 영업일(거래일) 판정 및 보정 도메인 서비스.

KRX 잠정실적 공시는 영업일에만 발생하므로, 추정된 발표일이 주말 또는
한국 공휴일에 해당하면 직전 영업일로 시프트한다. 직전 시프트를 사용하는
이유: 일반적으로 기업이 분기 마감 후 D+N 영업일 이내 발표하기로 약속한
경우 휴장일에 걸리면 미루지 않고 앞당겨 발표하는 관행이 더 일반적이다.

`holidays` 라이브러리에 의존하지만 도메인 순수성 원칙을 침해하지 않는다:
공휴일 데이터는 외부 시스템(API/DB/Redis 등)이 아닌 정적 룰셋이므로
표준 라이브러리에 준한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Set

import holidays


@lru_cache(maxsize=8)
def _kr_holiday_set(year: int) -> Set[date]:
    """연도별 한국 공휴일 집합을 캐싱하여 반환."""
    return set(holidays.SouthKorea(years=[year]).keys())


def is_business_day(d: date) -> bool:
    """주말(토·일) 또는 한국 공휴일이 아니면 True."""
    if d.weekday() >= 5:
        return False
    return d not in _kr_holiday_set(d.year)


def shift_to_previous_business_day(d: date) -> date:
    """주말/공휴일이면 직전 영업일로 시프트.

    최대 14일까지 거슬러 올라간다 (설/추석 연휴 + 주말 콤보 보호).
    """
    cursor = d
    for _ in range(14):
        if is_business_day(cursor):
            return cursor
        cursor -= timedelta(days=1)
    return cursor
