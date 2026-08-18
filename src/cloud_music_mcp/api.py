"""Thin, normalized wrapper around pyncm APIs."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pyncm import apis

from .auth import load_session


logger = logging.getLogger(__name__)
SEARCH_TYPES = {"song": 1, "album": 10, "artist": 100, "playlist": 1000}


def _ok(**payload: Any) -> dict[str, Any]:
    return {"success": True, **payload}


def _error(message: str, code: str = "api_error") -> dict[str, Any]:
    return {"success": False, "error": message, "error_code": code}


def _api_message(result: dict[str, Any], fallback: str) -> str:
    return str(result.get("message") or result.get("msg") or fallback)


def _artist_text(item: dict[str, Any]) -> str:
    artists = item.get("ar") or item.get("artists") or []
    names = [str(artist.get("name", "")).strip() for artist in artists]
    return " / ".join(name for name in names if name) or "未知"


def _song(item: dict[str, Any]) -> dict[str, Any]:
    album = item.get("al") or item.get("album") or {}
    return {
        "id": item.get("id"),
        "name": item.get("name", ""),
        "artist": _artist_text(item),
        "album": album.get("name", "") if isinstance(album, dict) else "",
    }


def _require_login() -> tuple[bool, str | None, dict[str, Any] | None]:
    logged_in, nickname = load_session()
    if logged_in:
        return True, nickname, None
    return False, None, _error("未登录，请先调用登录工具", "not_logged_in")


def get_song_detail(song_id: str | int) -> dict[str, Any]:
    load_session()
    try:
        result = apis.track.GetTrackDetail([int(song_id)])
        songs = result.get("songs") or []
        if not songs:
            return _error(f"未找到歌曲 ID {song_id}", "song_not_found")
        return _ok(song=_song(songs[0]))
    except (TypeError, ValueError):
        return _error(f"无效的歌曲 ID: {song_id}", "invalid_song_id")
    except Exception as exc:
        logger.exception("Failed to get song detail")
        return _error(str(exc))


def get_daily_recommendations() -> dict[str, Any]:
    logged_in, _, failure = _require_login()
    if not logged_in:
        return failure or _error("未登录", "not_logged_in")
    try:
        @apis.WeapiCryptoRequest
        def request_daily() -> tuple[str, dict[str, Any]]:
            return "/weapi/v1/discovery/recommend/songs", {
                "limit": 30,
                "offset": 0,
                "total": True,
            }

        result = request_daily()
        if result.get("code") != 200:
            return _error(_api_message(result, "获取每日推荐失败"))
        songs = [_song(song) for song in result.get("recommend") or []]
        return _ok(songs=songs, count=len(songs))
    except Exception as exc:
        logger.exception("Failed to get daily recommendations")
        return _error(str(exc))


def get_user_playlists() -> dict[str, Any]:
    logged_in, _, failure = _require_login()
    if not logged_in:
        return failure or _error("未登录", "not_logged_in")
    try:
        user_info = apis.login.GetCurrentLoginStatus()
        profile = user_info.get("profile") or {}
        user_id = profile.get("userId")
        if not user_id:
            return _error("登录状态中缺少用户 ID", "invalid_login_state")
        result = apis.user.GetUserPlaylists(user_id)
        if result.get("code") != 200:
            return _error(_api_message(result, "获取歌单失败"))
        playlists = []
        for playlist in result.get("playlist") or []:
            creator = playlist.get("creator") or {}
            playlists.append(
                {
                    "id": playlist.get("id"),
                    "name": playlist.get("name", ""),
                    "count": playlist.get("trackCount", 0),
                    "creator": creator.get("nickname", ""),
                    "is_mine": creator.get("userId") == user_id,
                }
            )
        return _ok(playlists=playlists, count=len(playlists))
    except Exception as exc:
        logger.exception("Failed to get user playlists")
        return _error(str(exc))


def search(keyword: str, category: str = "song", limit: int = 10) -> dict[str, Any]:
    load_session()
    keyword = keyword.strip()
    if not keyword:
        return _error("搜索关键词不能为空", "invalid_keyword")
    if category not in SEARCH_TYPES:
        return _error(
            f"不支持的搜索类型 {category}; 可选: {', '.join(SEARCH_TYPES)}",
            "invalid_category",
        )
    limit = max(1, min(int(limit), 50))
    try:
        result = apis.cloudsearch.GetSearchResult(
            keyword, stype=SEARCH_TYPES[category], limit=limit
        )
        if result.get("code") != 200:
            return _error(_api_message(result, "搜索失败"))
        payload = result.get("result") or {}
        items: list[dict[str, Any]] = []
        if category == "song":
            items = [_song(song) for song in payload.get("songs") or []]
        elif category == "album":
            items = [
                {
                    "id": album.get("id"),
                    "name": album.get("name", ""),
                    "artist": (album.get("artist") or {}).get("name", "未知"),
                }
                for album in payload.get("albums") or []
            ]
        elif category == "artist":
            items = [
                {"id": artist.get("id"), "name": artist.get("name", "")}
                for artist in payload.get("artists") or []
            ]
        else:
            items = [
                {
                    "id": playlist.get("id"),
                    "name": playlist.get("name", ""),
                    "count": playlist.get("trackCount", 0),
                }
                for playlist in payload.get("playlists") or []
            ]
        if not items:
            return _error("未找到结果", "no_results")
        return _ok(category=category, items=items, count=len(items))
    except (TypeError, ValueError):
        return _error("limit 必须是整数", "invalid_limit")
    except Exception as exc:
        logger.exception("Search failed")
        return _error(str(exc))


def get_playlist_detail(playlist_id: int) -> dict[str, Any]:
    load_session()
    try:
        result = apis.playlist.GetPlaylistInfo(int(playlist_id))
        if result.get("code") not in (None, 200):
            return _error(_api_message(result, "获取歌单失败"))
        playlist = result.get("playlist") or {}
        if not playlist:
            return _error("未找到歌单", "playlist_not_found")
        songs = [_song(track) for track in playlist.get("tracks") or []]
        return _ok(
            id=playlist.get("id", playlist_id),
            name=playlist.get("name", ""),
            count=playlist.get("trackCount", len(songs)),
            songs=songs,
        )
    except Exception as exc:
        logger.exception("Failed to get playlist")
        return _error(str(exc))


def create_playlist(name: str, privacy: bool = False) -> dict[str, Any]:
    logged_in, _, failure = _require_login()
    if not logged_in:
        return failure or _error("未登录", "not_logged_in")
    name = name.strip()
    if not name:
        return _error("歌单名称不能为空", "invalid_playlist_name")
    try:
        result = apis.playlist.SetCreatePlaylist(name, privacy)
        if result.get("code") not in (None, 200):
            return _error(_api_message(result, "创建歌单失败"))
        playlist = result.get("playlist") or {}
        if not playlist.get("id"):
            return _error("服务端未返回新歌单 ID", "invalid_api_response")
        return _ok(playlist_id=playlist["id"], name=playlist.get("name", name))
    except Exception as exc:
        logger.exception("Failed to create playlist")
        return _error(str(exc))


def add_to_playlist(playlist_id: int, track_ids: list[int]) -> dict[str, Any]:
    logged_in, _, failure = _require_login()
    if not logged_in:
        return failure or _error("未登录", "not_logged_in")
    if not isinstance(track_ids, list):
        track_ids = [track_ids]
    normalized = list(dict.fromkeys(int(track_id) for track_id in track_ids))
    if not normalized:
        return _error("track_ids 不能为空", "invalid_track_ids")
    try:
        result = apis.playlist.SetManipulatePlaylistTracks(
            trackIds=normalized, playlistId=int(playlist_id), op="add"
        )
        if result.get("code") != 200:
            return _error(_api_message(result, "添加歌曲失败"))
        return _ok(added_count=len(normalized), track_ids=normalized)
    except Exception as exc:
        logger.exception("Failed to add tracks")
        return _error(str(exc))


def get_album_info(album_id: int) -> dict[str, Any]:
    load_session()
    try:
        result = apis.album.GetAlbumInfo(int(album_id))
        album = result.get("album") or {}
        if not album:
            return _error("未找到专辑", "album_not_found")
        publish_time = album.get("publishTime") or 0
        publish_date = (
            datetime.fromtimestamp(publish_time / 1000).strftime("%Y-%m-%d")
            if publish_time
            else ""
        )
        songs = [_song(song) for song in result.get("songs") or []]
        return _ok(
            album={
                "id": album.get("id", album_id),
                "name": album.get("name", ""),
                "artist": (album.get("artist") or {}).get("name", "未知"),
                "publish_date": publish_date,
                "size": album.get("size", len(songs)),
            },
            songs=songs,
        )
    except Exception as exc:
        logger.exception("Failed to get album")
        return _error(str(exc))


def get_artist_info(artist_id: int) -> dict[str, Any]:
    load_session()
    try:
        detail = apis.artist.GetArtistDetails(int(artist_id))
        artist = (detail.get("data") or {}).get("artist") or {}
        if not artist:
            return _error("未找到歌手", "artist_not_found")
        tracks = apis.artist.GetArtistTracks(int(artist_id), limit=10)
        songs = [_song(song) for song in tracks.get("songs") or []]
        return _ok(
            artist={
                "name": artist.get("name", ""),
                "id": artist.get("id", artist_id),
                "album_count": artist.get("albumSize", 0),
                "song_count": artist.get("musicSize", 0),
                "description": (artist.get("briefDesc") or "")[:500],
            },
            songs=songs,
        )
    except Exception as exc:
        logger.exception("Failed to get artist")
        return _error(str(exc))


def get_my_subscriptions(category: str = "artists") -> dict[str, Any]:
    logged_in, _, failure = _require_login()
    if not logged_in:
        return failure or _error("未登录", "not_logged_in")
    if category not in {"artists", "albums"}:
        return _error("category 只能是 artists 或 albums", "invalid_category")
    try:
        result = (
            apis.user.GetUserAlbumSubs(limit=50)
            if category == "albums"
            else apis.user.GetUserArtistSubs(limit=50)
        )
        items = []
        for item in result.get("data") or []:
            entry = {"id": item.get("id"), "name": item.get("name", "")}
            if category == "albums":
                entry["artist"] = _artist_text(item)
            items.append(entry)
        return _ok(category=category, items=items, count=len(items))
    except Exception as exc:
        logger.exception("Failed to get subscriptions")
        return _error(str(exc))
