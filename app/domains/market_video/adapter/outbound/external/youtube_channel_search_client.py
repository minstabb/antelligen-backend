from datetime import datetime, timezone, timedelta

import httpx

from app.domains.market_video.application.port.youtube_channel_search_port import YoutubeChannelSearchPort
from app.domains.market_video.domain.entity.saved_youtube_video import SavedYoutubeVideo

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


class YoutubeChannelSearchClient(YoutubeChannelSearchPort):
    def __init__(self, api_key: str):
        self._api_key = api_key

    async def search_by_channels(
        self,
        channel_ids: list[str],
        recent_days: int,
        max_results_per_channel: int,
    ) -> list[SavedYoutubeVideo]:
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=recent_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        async with httpx.AsyncClient() as client:
            raw_items = await self._fetch_all_channels(
                client, channel_ids, published_after, max_results_per_channel
            )
            if not raw_items:
                return []

            video_stats = await self._fetch_statistics(
                client, [item["id"]["videoId"] for item in raw_items]
            )

        return self._build_entities(raw_items, video_stats)

    async def _fetch_all_channels(
        self,
        client: httpx.AsyncClient,
        channel_ids: list[str],
        published_after: str,
        max_results: int,
    ) -> list[dict]:
        results = []
        for channel_id in channel_ids:
            items = await self._search_channel(
                client, channel_id, published_after, max_results
            )
            results.extend(items)
        return results

    async def _search_channel(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
        published_after: str,
        max_results: int,
    ) -> list[dict]:
        try:
            response = await client.get(
                YOUTUBE_SEARCH_URL,
                params={
                    "key": self._api_key,
                    "channelId": channel_id,
                    "part": "snippet",
                    "type": "video",
                    "order": "date",
                    "publishedAfter": published_after,
                    "maxResults": max_results,
                },
            )
            response.raise_for_status()
            data = response.json()
            return [
                item for item in data.get("items", [])
                if item.get("id", {}).get("videoId")
            ]
        except Exception:
            return []

    async def _fetch_statistics(
        self,
        client: httpx.AsyncClient,
        video_ids: list[str],
    ) -> dict[str, int]:
        if not video_ids:
            return {}
        try:
            response = await client.get(
                YOUTUBE_VIDEOS_URL,
                params={
                    "key": self._api_key,
                    "id": ",".join(video_ids),
                    "part": "statistics",
                },
            )
            response.raise_for_status()
            data = response.json()
            return {
                item["id"]: int(item.get("statistics", {}).get("viewCount", 0))
                for item in data.get("items", [])
            }
        except Exception:
            return {}

    @staticmethod
    def _build_entities(
        raw_items: list[dict],
        video_stats: dict[str, int],
    ) -> list[SavedYoutubeVideo]:
        videos = []
        for item in raw_items:
            video_id = item["id"]["videoId"]
            snippet = item.get("snippet", {})
            thumbnails = snippet.get("thumbnails", {})
            thumbnail_url = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url", "")
            )
            videos.append(
                SavedYoutubeVideo(
                    video_id=video_id,
                    title=snippet.get("title", ""),
                    channel_name=snippet.get("channelTitle", ""),
                    published_at=snippet.get("publishedAt", ""),
                    view_count=video_stats.get(video_id, 0),
                    thumbnail_url=thumbnail_url,
                    video_url=f"https://www.youtube.com/watch?v={video_id}",
                )
            )
        return videos
