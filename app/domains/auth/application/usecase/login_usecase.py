from app.domains.auth.application.port.out.session_store_port import SessionStorePort
from app.domains.auth.application.request.login_request import LoginRequest
from app.domains.auth.application.response.login_response import LoginResponse
from app.domains.auth.domain.entity.session import Session
from app.domains.auth.domain.value_object.session_token import SessionToken


class LoginUseCase:
    def __init__(self, session_store: SessionStorePort, auth_password: str, session_ttl: int):
        self._session_store = session_store
        self._auth_password = auth_password
        self._session_ttl = session_ttl

    async def execute(self, request: LoginRequest) -> LoginResponse:
        if request.password != self._auth_password:
            raise ValueError("Invalid credentials")

        token = SessionToken.generate()
        session = Session(
            user_id=request.user_id,
            role=request.role,
            token=token.value,
            ttl_seconds=self._session_ttl,
        )
        await self._session_store.save(session)

        return LoginResponse(token=token.value, user_id=request.user_id, role=request.role)
