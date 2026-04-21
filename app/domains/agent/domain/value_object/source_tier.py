from enum import Enum


class SourceTier(str, Enum):
    HIGH = "HIGH"           # DART 공시, SEC, 미국 IB 공식 리포트, 기업 IR
    MEDIUM = "MEDIUM"       # Bloomberg, Reuters, WSJ, FT, 한경, 매경, 월가 애널리스트
    MEDIUM_LOW = "MEDIUM_LOW"  # 국내 IB 공식 리포트 (buy-bias 보정)
    LOW = "LOW"             # SNS, 일반 뉴스, 커뮤니티


# 기본 multiplier — settings에서 override 가능
_DEFAULT_WEIGHTS: dict[SourceTier, float] = {
    SourceTier.HIGH: 1.0,
    SourceTier.MEDIUM: 0.7,
    SourceTier.MEDIUM_LOW: 0.5,
    SourceTier.LOW: 0.3,
}


def default_multiplier(tier: SourceTier) -> float:
    return _DEFAULT_WEIGHTS.get(tier, 0.3)
