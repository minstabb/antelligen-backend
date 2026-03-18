from pydantic import BaseModel


class KakaoTokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    refresh_token_expires_in: int
