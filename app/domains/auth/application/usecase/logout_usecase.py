from app.domains.auth.application.port.out.session_store_port import SessionStorePort


class LogoutUseCase:
    def __init__(self, session_store: SessionStorePort):
        self._session_store = session_store

    async def execute(self, token: str) -> None:
        await self._session_store.delete(token)
