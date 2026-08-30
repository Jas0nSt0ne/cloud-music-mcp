#!/usr/bin/env python3
import os
import logging

# 在导入 FastMCP 之前设置环境变量以抑制日志和 Banner
os.environ["LOGURU_LEVEL"] = "WARNING"
os.environ["CI"] = "true"

from fastmcp import FastMCP

from cloud_music_mcp.log import setup_logging
from cloud_music_mcp.prompts import load_prompt
from cloud_music_mcp.auth import check_login_status, login_via_qrcode
from cloud_music_mcp.api import (
    get_daily_recommendations,
    get_user_playlists,
    search,
    get_playlist_detail,
    create_playlist,
    add_to_playlist,
    get_album_info,
    get_artist_info,
    get_my_subscriptions,
)
from cloud_music_mcp.client_control import get_client_status
from cloud_music_mcp.services import (
    play_daily_recommendation,
    play_song_by_id,
    search_and_play,
)

# 配置日志 (初始化)
setup_logging("cloud_music_mcp")
logger = logging.getLogger(__name__)

# 抑制 FastMCP 和相关库的日志
logging.getLogger("fastmcp").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# 抑制 pyncm 的日志输出，防止溢出到 LLM client
logging.getLogger("pyncm").setLevel(logging.WARNING)
logging.getLogger("pyncm.api").setLevel(logging.WARNING)
logging.getLogger("pyncm.helper").setLevel(logging.WARNING)

# 初始化 MCP Server
mcp = FastMCP("NetEase-Cloud-Music-MCP")


@mcp.tool(description=load_prompt("cloud_music_status"))
def cloud_music_status():
    logger.info("Calling cloud_music_status")
    return {
        "success": True,
        "account": check_login_status(),
        "client": get_client_status(),
    }


@mcp.tool(description=load_prompt("cloud_music_login"))
def cloud_music_login():
    logger.info("Calling cloud_music_login")
    return login_via_qrcode()


@mcp.tool(description=load_prompt("cloud_music_get_daily_recommend"))
def cloud_music_get_daily_recommend(limit: int = 50):
    logger.info("Calling cloud_music_get_daily_recommend")
    result = get_daily_recommendations()
    if not result["success"]:
        return result
    limit = max(1, min(int(limit), len(result["songs"])))
    songs = [
        {"position": position, **song}
        for position, song in enumerate(result["songs"][:limit], 1)
    ]
    return {"success": True, "count": len(result["songs"]), "songs": songs}


@mcp.tool(description=load_prompt("cloud_music_my_playlists"))
def cloud_music_my_playlists():
    logger.info("Calling cloud_music_my_playlists")
    result = get_user_playlists()
    if result["success"]:
        text = "我的歌单:\n"
        for pl in result["playlists"]:
            mark = (
                "❤️ " if "喜欢" in pl["name"] else ("👤 " if pl["is_mine"] else "收藏 ")
            )
            text += f"{mark} {pl['name']} (ID: {pl['id']}, {pl['count']}首)\n"
        return text
    else:
        return f"获取失败: {result.get('error')}"


@mcp.tool(description=load_prompt("cloud_music_search"))
def cloud_music_search(keyword: str, category: str = "song", limit: int = 10):
    logger.info(f"Calling cloud_music_search with keyword: {keyword}, category: {category}")
    return search(keyword, category=category, limit=limit)


@mcp.tool(description=load_prompt("cloud_music_playlist_detail"))
def cloud_music_playlist_detail(playlist_id: int):
    logger.info(f"Calling cloud_music_playlist_detail with playlist_id: {playlist_id}")
    result = get_playlist_detail(playlist_id)
    if result["success"]:
        text = f"📋 歌单: {result['name']} ({result['count']}首)\n"
        for i, song in enumerate(result["songs"], 1):
            text += f"{i}. {song['name']} - {song['artist']} (ID: {song['id']})\n"
        return text
    else:
        return f"获取失败: {result.get('error')}"


@mcp.tool(description=load_prompt("cloud_music_create_playlist"))
def cloud_music_create_playlist(name: str, privacy: bool = False):
    logger.info(f"Calling cloud_music_create_playlist with name: {name}")
    result = create_playlist(name, privacy)
    if result["success"]:
        return f"歌单创建成功: {result['name']} (ID: {result['playlist_id']})"
    else:
        return f"创建失败: {result.get('error')}"


@mcp.tool(description=load_prompt("cloud_music_add_to_playlist"))
def cloud_music_add_to_playlist(playlist_id: int, track_ids: list[int]):
    logger.info(f"Calling cloud_music_add_to_playlist with playlist_id: {playlist_id}, track_ids: {track_ids}")
    result = add_to_playlist(playlist_id, track_ids)
    if result["success"]:
        return f"成功添加 {result['added_count']} 首歌曲到歌单 {playlist_id}"
    else:
        return f"添加失败: {result.get('error')}"


@mcp.tool(description=load_prompt("cloud_music_album_info"))
def cloud_music_album_info(album_id: int):
    logger.info(f"Calling cloud_music_album_info with album_id: {album_id}")
    result = get_album_info(album_id)
    if result["success"]:
        album = result["album"]
        text = f"💿 专辑: {album['name']} - {album['artist']}\n"
        text += f"📅 发行日期: {album['publish_date']} | 共 {album['size']} 首\n"
        for i, song in enumerate(result["songs"], 1):
            text += f"{i}. {song['name']} - {song['artist']} (ID: {song['id']})\n"
        return text
    else:
        return f"获取失败: {result.get('error')}"


@mcp.tool(description=load_prompt("cloud_music_artist_info"))
def cloud_music_artist_info(artist_id: int):
    logger.info(f"Calling cloud_music_artist_info with artist_id: {artist_id}")
    result = get_artist_info(artist_id)
    if result["success"]:
        artist = result["artist"]
        text = f"🎤 歌手: {artist['name']} (ID: {artist['id']})\n"
        text += f"📊 专辑 {artist['album_count']} 张 | 歌曲 {artist['song_count']} 首\n"
        if artist["description"]:
            text += f"📝 {artist['description']}\n"
        text += "\n🔥 热门歌曲:\n"
        for i, song in enumerate(result["songs"], 1):
            text += f"{i}. {song['name']} (ID: {song['id']})\n"
        return text
    else:
        return f"获取失败: {result.get('error')}"


@mcp.tool(description=load_prompt("cloud_music_my_subscriptions"))
def cloud_music_my_subscriptions(category: str = "artists"):
    logger.info(f"Calling cloud_music_my_subscriptions with category: {category}")
    result = get_my_subscriptions(category)
    if result["success"]:
        type_name = "歌手" if category == "artists" else "专辑"
        text = f"📌 收藏的{type_name} ({len(result['items'])}个):\n"
        for i, item in enumerate(result["items"], 1):
            if category == "albums":
                text += f"{i}. {item['name']} - {item['artist']} (ID: {item['id']})\n"
            else:
                text += f"{i}. {item['name']} (ID: {item['id']})\n"
        return text
    else:
        return f"获取失败: {result.get('error')}"


@mcp.tool(description=load_prompt("cloud_music_play"))
def cloud_music_play(id: str, type: str = "song"):
    logger.info(f"Calling cloud_music_play with id: {id}, type: {type}")
    return play_song_by_id(id, type)


@mcp.tool(description=load_prompt("cloud_music_play_daily"))
def cloud_music_play_daily(position: int):
    """Play one item from today's recommendations by one-based position."""
    logger.info("Calling cloud_music_play_daily with position: %s", position)
    return play_daily_recommendation(position)


@mcp.tool(description=load_prompt("cloud_music_search_and_play"))
def cloud_music_search_and_play(keyword: str, position: int = 1):
    """Search songs and play one result by one-based position."""
    logger.info(
        "Calling cloud_music_search_and_play with keyword: %s, position: %s",
        keyword,
        position,
    )
    return search_and_play(keyword, position)


if __name__ == "__main__":
    mcp.run(show_banner=False)
