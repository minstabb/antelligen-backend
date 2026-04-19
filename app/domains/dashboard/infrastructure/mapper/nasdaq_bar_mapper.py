from app.domains.dashboard.domain.entity.nasdaq_bar import NasdaqBar
from app.domains.dashboard.infrastructure.orm.nasdaq_bar_orm import NasdaqBarOrm


class NasdaqBarMapper:

    @staticmethod
    def to_entity(orm: NasdaqBarOrm) -> NasdaqBar:
        return NasdaqBar(
            bar_id=orm.id,
            bar_date=orm.bar_date,
            open=orm.open,
            high=orm.high,
            low=orm.low,
            close=orm.close,
            volume=orm.volume,
        )

    @staticmethod
    def to_orm(entity: NasdaqBar) -> NasdaqBarOrm:
        return NasdaqBarOrm(
            bar_date=entity.bar_date,
            open=entity.open,
            high=entity.high,
            low=entity.low,
            close=entity.close,
            volume=entity.volume,
        )
