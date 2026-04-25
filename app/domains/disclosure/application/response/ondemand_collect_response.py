
from pydantic import BaseModel


class OndemandCollectResponse(BaseModel):
    corp_code: str
    corp_name: str
    total_fetched: int
    saved_count: int
    duplicate_skipped: int
    coverage_updated: bool
    message: str
