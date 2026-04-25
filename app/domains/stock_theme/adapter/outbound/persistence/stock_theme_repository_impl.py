from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.stock_theme.application.port.out.stock_theme_repository_port import StockThemeRepositoryPort
from app.domains.stock_theme.domain.entity.stock_theme import StockTheme
from app.domains.stock_theme.infrastructure.orm.stock_theme_orm import StockThemeOrm


class StockThemeRepositoryImpl(StockThemeRepositoryPort):
    def __init__(self, db: AsyncSession):
        self._db = db

    async def save_all(self, stock_themes: list[StockTheme]) -> None:
        if not stock_themes:
            return
        values = [
            {"name": entity.name, "code": entity.code, "themes": entity.themes}
            for entity in stock_themes
        ]
        stmt = (
            insert(StockThemeOrm)
            .values(values)
            .on_conflict_do_nothing(index_elements=["name"])
        )
        await self._db.execute(stmt)
        await self._db.commit()

    async def find_all(self) -> list[StockTheme]:
        stmt = select(StockThemeOrm)
        result = await self._db.execute(stmt)
        all_orms = result.scalars().all()

        # Deduplicate by code, merging themes (guards against legacy duplicate rows)
        code_themes: dict[str, set] = {}
        code_name: dict[str, str] = {}
        for orm in all_orms:
            if orm.code not in code_themes:
                code_themes[orm.code] = set(orm.themes)
                code_name[orm.code] = orm.name
            else:
                code_themes[orm.code].update(orm.themes)

        return [
            StockTheme(id=None, name=code_name[code], code=code, themes=list(themes))
            for code, themes in code_themes.items()
        ]

    async def find_all_by_theme(self, theme_name: str) -> list[StockTheme]:
        all_stocks = await self.find_all()
        return [s for s in all_stocks if theme_name in s.themes]

    async def exists_any(self) -> bool:
        stmt = select(func.count()).select_from(StockThemeOrm)
        result = await self._db.execute(stmt)
        return result.scalar() > 0
