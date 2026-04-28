"""
SNS 수집 결과 응답 DTO
======================
CollectSnsPostsUseCase.execute() 반환값.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CollectSnsPostsResponse:
    ticker: str
    total_collected: int                        # 수집된 총 게시물 수
    total_saved: int                            # 실제 DB에 저장된 수 (중복 제외)
    skipped_duplicates: int                     # 중복으로 skip된 수
    per_platform: dict[str, dict] = field(default_factory=dict)
    # 예: {"reddit": {"collected": 30, "saved": 28}}
    elapsed_ms: int = 0
