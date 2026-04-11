from pydantic import BaseModel, Field


class SaveUserArticleRequest(BaseModel):
    title: str = Field(..., min_length=1, description="기사 제목")
    link: str = Field(..., min_length=1, description="원문 링크")
    source: str | None = Field(None, description="출처")
    published_at: str | None = Field(None, description="게시 시간")
    snippet: str | None = Field(None, description="기사 요약")
