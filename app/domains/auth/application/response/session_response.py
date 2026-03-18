from pydantic import BaseModel


class SessionResponse(BaseModel):
    user_id: str
    role: str
    token: str
