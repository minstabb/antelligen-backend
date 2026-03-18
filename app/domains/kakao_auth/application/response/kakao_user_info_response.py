from typing import Optional

from pydantic import BaseModel


class KakaoUserInfoResponse(BaseModel):
    kakao_id: int
    nickname: Optional[str]
    email: Optional[str]
