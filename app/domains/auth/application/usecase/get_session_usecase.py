from typing import Optional

from app.domains.auth.application.port.out.session_store_port import SessionStorePort
from app.domains.auth.application.response.session_response import SessionResponse


class GetSessionUseCase:
    def __init__(self, session_store: SessionStorePort):
        self._session_store = session_store

    async def execute(self, token: str) -> Optional[SessionResponse]:
        session = await self._session_store.find_by_token(token)
        if not session:
            return None
        return SessionResponse(user_id=session.user_id, role=session.role, token=session.token)
