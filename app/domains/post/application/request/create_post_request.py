from pydantic import BaseModel, field_validator


class CreatePostRequest(BaseModel):
    title: str
    content: str

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("제목은 비어 있을 수 없습니다")
        return v.strip()

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("본문은 비어 있을 수 없습니다")
        return v.strip()
