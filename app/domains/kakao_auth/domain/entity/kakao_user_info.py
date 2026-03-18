from dataclasses import dataclass
from typing import Optional


@dataclass
class KakaoUserInfo:
    kakao_id: int
    nickname: Optional[str]
    email: Optional[str]
