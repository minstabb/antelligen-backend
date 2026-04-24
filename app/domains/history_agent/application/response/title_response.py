from datetime import date
from typing import List

from pydantic import BaseModel


class TitleItem(BaseModel):
    date: date
    type: str
    detail_hash: str
    title: str


class TitleBatchResponse(BaseModel):
    titles: List[TitleItem]
