"""Build a NetEase playlist from a structured BGM list."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from typing import Any, Callable

from .api import (
    add_to_playlist,
    create_playlist,
    get_playlist_detail,
    get_user_playlists,
    search,
)


SearchFn = Callable[..., dict[str, Any]]
ApiFn = Callable[..., dict[str, Any]]


def _error(message: str, code: str, **payload: Any) -> dict[str, Any]:
    return {"success": False, "error": message, "error_code": code, **payload}


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(character for character in value if character.isalnum())


def _artist_tokens(value: str) -> set[str]:
    parts = re.split(
        r"\s*(?:/|,|&|，|、|;|；|\+)\s*|\s+(?:feat\.?|ft\.?)\s+",
        value or "",
        flags=re.IGNORECASE,
    )
    tokens = {_normalize(part) for part in parts if _normalize(part)}
    normalized = _normalize(value)
    if normalized:
        tokens.add(normalized)
    return tokens


def _artists_overlap(left: str, right: str) -> bool:
    left_tokens = _artist_tokens(left)
    right_tokens = _artist_tokens(right)
    if left_tokens & right_tokens:
        return True
    return any(
        min(len(left_token), len(right_token)) >= 4
        and (left_token in right_token or right_token in left_token)
        for left_token in left_tokens
        for right_token in right_tokens
    )


def _titles_close(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if min(len(left), len(right)) >= 2 and (left in right or right in left):
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.72


def build_playlist_name(label: str = "", today: date | None = None) -> str:
    """Return YYYYMMDD immediately followed by the user label."""
    date_text = (today or date.today()).strftime("%Y%m%d")
    clean_label = " ".join(str(label or "").split()) or "歌单"
    if clean_label.startswith(date_text):
        return clean_label
    return f"{date_text}{clean_label}"


def _prepare_tracks(
    tracks: list[dict[str, str]] | Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[int]]:
    if not isinstance(tracks, list):
        return [], [], [1]

    unique: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    invalid_positions: list[int] = []
    seen: dict[tuple[str, str], int] = {}
    for position, item in enumerate(tracks, 1):
        if not isinstance(item, dict):
            invalid_positions.append(position)
            continue
        name = str(item.get("name") or "").strip()
        artist = str(item.get("artist") or "").strip()
        if not name:
            invalid_positions.append(position)
            continue
        key = (_normalize(name), _normalize(artist))
        if not key[0]:
            invalid_positions.append(position)
            continue
        if key in seen:
            duplicates.append(
                {
                    "source_position": position,
                    "duplicate_of": seen[key],
                    "source": {"name": name, "artist": artist},
                }
            )
            continue
        seen[key] = position
        unique.append(
            {
                "source_position": position,
                "source": {"name": name, "artist": artist},
            }
        )
    return unique, duplicates, invalid_positions


def _candidate_view(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate.get("id"),
        "name": candidate.get("name", ""),
        "artist": candidate.get("artist", ""),
        "album": candidate.get("album", ""),
    }


def _search_track(track: dict[str, Any], search_fn: SearchFn) -> dict[str, Any]:
    source = track["source"]
    queries = [f"{source['name']} {source['artist']}".strip()]
    if source["artist"]:
        queries.append(source["name"])

    candidates: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    errors: list[dict[str, str]] = []
    for query in queries:
        result = search_fn(query, category="song", limit=10)
        if not result.get("success"):
            if result.get("error_code") != "no_results":
                errors.append(
                    {
                        "query": query,
                        "error": str(result.get("error") or "搜索失败"),
                        "error_code": str(result.get("error_code") or "api_error"),
                    }
                )
            continue
        for candidate in result.get("items") or []:
            try:
                candidate_id = int(candidate.get("id"))
            except (TypeError, ValueError):
                continue
            if candidate_id not in seen_ids:
                seen_ids.add(candidate_id)
                candidates.append(_candidate_view(candidate))

    source_name = _normalize(source["name"])
    exact_title = [
        candidate
        for candidate in candidates
        if _normalize(str(candidate.get("name") or "")) == source_name
    ]
    if source["artist"]:
        exact_full_artist = [
            candidate
            for candidate in exact_title
            if _normalize(str(candidate.get("artist") or ""))
            == _normalize(source["artist"])
        ]
        if exact_full_artist:
            result = {**track, "status": "matched", "match": exact_full_artist[0]}
            if len(exact_full_artist) > 1:
                result["alternate_matches"] = exact_full_artist[1:5]
            return result
        exact_artist = [
            candidate
            for candidate in exact_title
            if _artists_overlap(source["artist"], str(candidate.get("artist") or ""))
        ]
        if len(exact_artist) == 1:
            return {**track, "status": "matched", "match": exact_artist[0]}
        if len(exact_artist) > 1:
            return {**track, "status": "ambiguous", "candidates": exact_artist[:5]}
    elif len(exact_title) == 1:
        return {**track, "status": "matched", "match": exact_title[0]}

    if exact_title:
        return {**track, "status": "ambiguous", "candidates": exact_title[:5]}

    close_candidates = [
        candidate
        for candidate in candidates
        if _titles_close(
            source_name, _normalize(str(candidate.get("name") or ""))
        )
    ]
    if close_candidates:
        return {**track, "status": "ambiguous", "candidates": close_candidates[:5]}
    if errors and not candidates:
        return {**track, "status": "search_error", "errors": errors}
    return {**track, "status": "not_found", "candidates": candidates[:3]}


def preview_bgm_playlist(
    tracks: list[dict[str, str]],
    playlist_label: str = "",
    *,
    today: date | None = None,
    search_fn: SearchFn = search,
) -> dict[str, Any]:
    """Search a screenshot-derived track list without changing account data."""
    prepared, duplicates, invalid_positions = _prepare_tracks(tracks)
    if not prepared:
        return _error(
            "没有可识别的歌曲；每项至少需要非空 name",
            "invalid_tracks",
            invalid_positions=invalid_positions,
        )

    results = [_search_track(track, search_fn) for track in prepared]
    counts = {
        status: sum(item["status"] == status for item in results)
        for status in ("matched", "ambiguous", "not_found", "search_error")
    }
    return {
        "success": True,
        "playlist_name": build_playlist_name(playlist_label, today),
        "source_count": len(tracks),
        "unique_count": len(prepared),
        "matched_count": counts["matched"],
        "ambiguous_count": counts["ambiguous"],
        "not_found_count": counts["not_found"],
        "search_error_count": counts["search_error"],
        "invalid_positions": invalid_positions,
        "duplicate_sources": duplicates,
        "results": results,
    }


def import_bgm_playlist(
    tracks: list[dict[str, str]],
    playlist_label: str = "",
    privacy: bool = False,
    *,
    today: date | None = None,
    search_fn: SearchFn = search,
    get_playlists_fn: ApiFn = get_user_playlists,
    get_playlist_fn: ApiFn = get_playlist_detail,
    create_playlist_fn: ApiFn = create_playlist,
    add_tracks_fn: ApiFn = add_to_playlist,
) -> dict[str, Any]:
    """Import all safe matches and leave ambiguous tracks for user review."""
    preview = preview_bgm_playlist(
        tracks, playlist_label, today=today, search_fn=search_fn
    )
    if not preview.get("success"):
        return preview

    matched = [item for item in preview["results"] if item["status"] == "matched"]
    if not matched:
        return _error(
            "没有高置信匹配，未创建或修改歌单",
            "no_safe_matches",
            preview=preview,
        )

    playlists_result = get_playlists_fn()
    if not playlists_result.get("success"):
        return _error(
            str(playlists_result.get("error") or "获取歌单失败"),
            str(playlists_result.get("error_code") or "playlist_lookup_failed"),
            preview=preview,
        )

    playlist_name = preview["playlist_name"]
    existing_playlist = next(
        (
            playlist
            for playlist in playlists_result.get("playlists") or []
            if playlist.get("is_mine") and playlist.get("name") == playlist_name
        ),
        None,
    )
    existing_track_ids: set[int] = set()
    action = "created"
    if existing_playlist:
        action = "reused"
        playlist_id = int(existing_playlist["id"])
        detail = get_playlist_fn(playlist_id)
        if not detail.get("success"):
            return _error(
                str(detail.get("error") or "获取已有歌单详情失败"),
                str(detail.get("error_code") or "playlist_detail_failed"),
                playlist_id=playlist_id,
                playlist_name=playlist_name,
                preview=preview,
            )
        existing_track_ids = {
            int(song["id"])
            for song in detail.get("songs") or []
            if song.get("id") is not None
        }
    else:
        created = create_playlist_fn(playlist_name, privacy)
        if not created.get("success"):
            return _error(
                str(created.get("error") or "创建歌单失败"),
                str(created.get("error_code") or "playlist_create_failed"),
                preview=preview,
            )
        playlist_id = int(created["playlist_id"])

    ordered_track_ids: list[int] = []
    duplicate_matches: list[dict[str, Any]] = []
    seen_track_ids = set(existing_track_ids)
    for item in matched:
        track_id = int(item["match"]["id"])
        if track_id in seen_track_ids:
            duplicate_matches.append(
                {
                    "source_position": item["source_position"],
                    "track_id": track_id,
                    "reason": (
                        "already_in_playlist"
                        if track_id in existing_track_ids
                        else "same_match_in_request"
                    ),
                }
            )
            continue
        seen_track_ids.add(track_id)
        ordered_track_ids.append(track_id)

    if ordered_track_ids:
        # NetEase prepends a batch in reverse order. Reverse the request so the
        # visible playlist follows the source screenshot from top to bottom.
        added = add_tracks_fn(playlist_id, list(reversed(ordered_track_ids)))
        if not added.get("success"):
            return _error(
                str(added.get("error") or "添加歌曲失败"),
                str(added.get("error_code") or "playlist_add_failed"),
                partial_mutation=action == "created",
                playlist_id=playlist_id,
                playlist_name=playlist_name,
                preview=preview,
            )

    return {
        "success": True,
        "playlist_id": playlist_id,
        "playlist_name": playlist_name,
        "playlist_action": action,
        "added_count": len(ordered_track_ids),
        "added_track_ids_in_source_order": ordered_track_ids,
        "skipped_existing_or_duplicate": duplicate_matches,
        "needs_confirmation": preview["ambiguous_count"] > 0,
        "preview": preview,
    }
