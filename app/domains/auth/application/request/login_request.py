from pydantic import BaseModel


class LoginRequest(BaseModel):
    user_id: str
    password: str
    role: str = "USER"
