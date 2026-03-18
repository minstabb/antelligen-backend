from pydantic import BaseModel


class LoginResponse(BaseModel):
    token: str
    user_id: str
    role: str
