from datetime import datetime


class UserSavedArticle:
    """사용자별 관심 기사 도메인 엔티티"""

    def __init__(
        self,
        account_id: int,
        title: str,
        link: str,
        source: str | None = None,
        published_at: str | None = None,
        snippet: str | None = None,
        article_id: int | None = None,
        saved_at: datetime | None = None,
    ):
        self.article_id = article_id
        self.account_id = account_id
        self.title = title
        self.link = link
        self.source = source
        self.published_at = published_at
        self.snippet = snippet
        self.saved_at = saved_at
