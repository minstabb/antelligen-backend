import secrets


class SessionToken:
    def __init__(self, value: str):
        self._value = value

    @classmethod
    def generate(cls) -> "SessionToken":
        return cls(secrets.token_urlsafe(32))

    @property
    def value(self) -> str:
        return self._value
