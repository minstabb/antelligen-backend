from abc import ABC, abstractmethod

from app.domains.account.domain.entity.account import Account


class AccountSavePort(ABC):

    @abstractmethod
    async def save(self, account: Account) -> Account:
        pass
