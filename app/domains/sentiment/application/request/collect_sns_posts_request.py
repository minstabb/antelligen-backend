"""
SNS 게시물 수집 요청 DTO
"""
from pydantic import BaseModel, Field


class CollectSnsPostsRequest(BaseModel):
    ticker: str = Field(..., description="종목 티커 (005930 또는 AAPL)")
    limit_per_platform: int = Field(50, description="플랫폼별 최대 수집 개수")
