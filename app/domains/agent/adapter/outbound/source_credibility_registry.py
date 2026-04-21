from urllib.parse import urlparse

from app.domains.agent.application.port.source_credibility_port import SourceCredibilityPort
from app.domains.agent.domain.value_object.sector import Sector
from app.domains.agent.domain.value_object.source_tier import SourceTier

# 도메인 → 기본 티어 매핑
_DOMAIN_TIER_MAP: dict[str, SourceTier] = {
    # HIGH: 공식 공시·IR
    "dart.fss.or.kr": SourceTier.HIGH,
    "sec.gov": SourceTier.HIGH,
    "edgar.sec.gov": SourceTier.HIGH,
    # MEDIUM: 글로벌 경제전문지
    "bloomberg.com": SourceTier.MEDIUM,
    "reuters.com": SourceTier.MEDIUM,
    "wsj.com": SourceTier.MEDIUM,
    "ft.com": SourceTier.MEDIUM,
    "cnbc.com": SourceTier.MEDIUM,
    "marketwatch.com": SourceTier.MEDIUM,
    "barrons.com": SourceTier.MEDIUM,
    "seekingalpha.com": SourceTier.MEDIUM,
    # MEDIUM: 국내 경제전문지
    "hankyung.com": SourceTier.MEDIUM,
    "mk.co.kr": SourceTier.MEDIUM,
    "edaily.co.kr": SourceTier.MEDIUM,
    "etnews.com": SourceTier.MEDIUM,
    "sedaily.com": SourceTier.MEDIUM,
    # MEDIUM_LOW: 국내 증권사 리서치
    "samsung-pop.com": SourceTier.MEDIUM_LOW,
    "miraeassetdaewoo.com": SourceTier.MEDIUM_LOW,
    "nhqv.com": SourceTier.MEDIUM_LOW,
    "kiwoom.com": SourceTier.MEDIUM_LOW,
    "shinyoung.com": SourceTier.MEDIUM_LOW,
    "koreainvestment.com": SourceTier.MEDIUM_LOW,
    # LOW: 일반 뉴스·SNS·커뮤니티
    "naver.com": SourceTier.LOW,
    "n.news.naver.com": SourceTier.LOW,
    "daum.net": SourceTier.LOW,
    "news.daum.net": SourceTier.LOW,
    "youtube.com": SourceTier.LOW,
    "youtu.be": SourceTier.LOW,
    "twitter.com": SourceTier.LOW,
    "x.com": SourceTier.LOW,
    "instagram.com": SourceTier.LOW,
    "reddit.com": SourceTier.LOW,
    "dcinside.com": SourceTier.LOW,
    "ruliweb.com": SourceTier.LOW,
    "blind.com": SourceTier.LOW,
    "clien.net": SourceTier.LOW,
}

# 엔터테인먼트 섹터에서 SNS/영상 플랫폼은 LOW → MEDIUM 승격
_SOCIAL_DOMAINS = {"youtube.com", "youtu.be", "twitter.com", "x.com", "instagram.com"}

# 섹터별 SNS override: sector → (승격 대상 도메인 집합, 새 티어)
_SECTOR_OVERRIDE: dict[Sector, tuple[set[str], SourceTier]] = {
    Sector.ENTERTAINMENT: (_SOCIAL_DOMAINS, SourceTier.MEDIUM),
}


class SourceCredibilityRegistry(SourceCredibilityPort):
    """출처 URL/이름 → SourceTier 분류 레지스트리"""

    def classify(self, source_url_or_name: str, sector: Sector = Sector.UNKNOWN) -> SourceTier:
        domain = _extract_domain(source_url_or_name)
        tier = _DOMAIN_TIER_MAP.get(domain, SourceTier.LOW)

        # 섹터 override 적용
        if sector in _SECTOR_OVERRIDE:
            override_domains, upgraded_tier = _SECTOR_OVERRIDE[sector]
            if domain in override_domains and tier == SourceTier.LOW:
                tier = upgraded_tier

        return tier


def _extract_domain(source: str) -> str:
    """URL 또는 출처 이름에서 도메인 추출."""
    source = source.strip().lower()
    if source.startswith("http"):
        parsed = urlparse(source)
        domain = parsed.netloc
        # www. 접두사 제거
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    # URL이 아닌 경우 그대로 사용 (소스명 직접 매핑 시도)
    return source
