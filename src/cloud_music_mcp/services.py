"""Testable application services used by MCP tool adapters."""

from __future__ import annotations

import logging
from typing import Any

from .api import get_daily_recommendations, get_playlist_detail, get_song_detail, search
from .client_control import ClientControlError, play_playlist, play_song


logger = logging.getLogger(__name__)


def play_song_by_id(song_id: str | int, playback_type: str = "song") -> dict[str, Any]:
    if playback_type == "playlist":
        return play_playlist_by_id(song_id)
    if playback_type != "song":
        return {
            "success": False,
            "error": "新版客户端控制目前只支持单曲播放，未发送未经验证的歌单播放指令",
            "error_code": "unsupported_playback_type",
        }
    detail = get_song_detail(song_id)
    if not detail["success"]:
        return detail
    return play_song_record(detail["song"])


def play_playlist_by_id(playlist_id: str | int) -> dict[str, Any]:
    detail = get_playlist_detail(int(playlist_id))
    if not detail["success"]:
        return detail
    songs = detail.get("songs") or []
    if not songs:
        return {
            "success": False,
            "error": "歌单为空，无法开始播放",
            "error_code": "empty_playlist",
            "playlist_id": int(playlist_id),
        }
    try:
        result = play_playlist(detail["id"], detail["name"], songs[0])
        return {
            **result,
            "message": f"网易云客户端正在播放歌单: {detail['name']}",
            "playlist": {
                "id": detail["id"],
                "name": detail["name"],
                "count": detail["count"],
            },
        }
    except ClientControlError as exc:
        logger.error("Playlist playback failed: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "error_code": exc.code,
            "playlist": {
                "id": detail["id"],
                "name": detail["name"],
                "count": detail["count"],
            },
        }


def play_daily_recommendation(position: int) -> dict[str, Any]:
    result = get_daily_recommendations()
    if not result["success"]:
        return result
    songs = result["songs"]
    if position < 1 or position > len(songs):
        return {
            "success": False,
            "error": f"position 必须在 1..{len(songs)} 之间",
            "error_code": "invalid_position",
        }
    return play_song_record(songs[position - 1], position=position, source="daily")


def search_and_play(keyword: str, position: int = 1) -> dict[str, Any]:
    if position < 1:
        return {
            "success": False,
            "error": "position 必须大于等于 1",
            "error_code": "invalid_position",
        }
    result = search(keyword, category="song", limit=max(position, 10))
    if not result["success"]:
        return result
    items = result["items"]
    if position > len(items):
        return {
            "success": False,
            "error": f"position 必须在 1..{len(items)} 之间",
            "error_code": "invalid_position",
        }
    return play_song_record(items[position - 1], position=position, source="search")


def play_song_record(song: dict[str, Any], **context: Any) -> dict[str, Any]:
    try:
        result = play_song(song["id"], song["name"], song["artist"])
        return {
            **result,
            "message": f"网易云客户端正在播放: {song['name']} - {song['artist']}",
            "song": song,
            **context,
        }
    except ClientControlError as exc:
        logger.error("Playback failed: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "error_code": exc.code,
            "song": song,
            **context,
        }
