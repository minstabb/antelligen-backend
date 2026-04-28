"""
SNS 감정분석 요청 DTO
"""
from pydantic import BaseModel, Field


class AnalyzeSnsSignalRequest(BaseModel):
    ticker: str = Field(..., description="종목 티커")
    lookback_limit: int = Field(100, description="조회할 최근 게시물 수")
