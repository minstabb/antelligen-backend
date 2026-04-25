from typing import Optional

from pydantic import BaseModel


class WatchlistNewsItem(BaseModel):
    title: str
    description: Optional[str] = None
    url: str
    published_at: Optional[str] = None
    stock_code: Optional[str] = None
    stock_name: Optional[str] = None


class WatchlistNewsFeedResponse(BaseModel):
    has_watchlist: bool
    items: list[WatchlistNewsItem]
    total: int
