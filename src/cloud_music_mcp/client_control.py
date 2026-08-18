"""Control and verify playback in the official NetEase Cloud Music client."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypeVar

import websockets

from .windows_desktop import (
    WindowInfo,
    current_desktop_name,
    find_windows_by_class,
    input_desktop_name,
    launch_process_on_desktop,
)


MAIN_WINDOW_CLASSES = frozenset({"OrpheusBrowserHost"})
T = TypeVar("T")


class ClientControlError(RuntimeError):
    """Base error returned to MCP callers without claiming false success."""

    def __init__(self, message: str, *, code: str = "client_control_error") -> None:
        super().__init__(message)
        self.code = code


class ClientNotReadyError(ClientControlError):
    def __init__(self, message: str, *, code: str = "client_not_ready") -> None:
        super().__init__(message, code=code)


class PlaybackVerificationError(ClientControlError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="playback_not_verified")


@dataclass(frozen=True, slots=True)
class ClientConfig:
    debug_host: str = "127.0.0.1"
    debug_port: int = 9222
    desktop_name: str = "Default"
    request_timeout: float = 2.0
    launch_timeout: float = 20.0
    search_timeout: float = 12.0
    playback_timeout: float = 12.0

    @classmethod
    def from_env(cls) -> "ClientConfig":
        return cls(
            debug_host=os.getenv("CLOUD_MUSIC_DEBUG_HOST", "127.0.0.1"),
            debug_port=_env_int("CLOUD_MUSIC_DEBUG_PORT", 9222, 1, 65535),
            desktop_name=os.getenv("CLOUD_MUSIC_DESKTOP", "Default"),
            request_timeout=_env_float("CLOUD_MUSIC_REQUEST_TIMEOUT", 2.0, 0.2),
            launch_timeout=_env_float("CLOUD_MUSIC_LAUNCH_TIMEOUT", 20.0, 2.0),
            search_timeout=_env_float("CLOUD_MUSIC_SEARCH_TIMEOUT", 12.0, 2.0),
            playback_timeout=_env_float("CLOUD_MUSIC_PLAYBACK_TIMEOUT", 12.0, 2.0),
        )

    @property
    def debug_endpoint(self) -> str:
        return f"http://{self.debug_host}:{self.debug_port}/json/list"


@dataclass(frozen=True, slots=True)
class PlaybackResult:
    success: bool
    song_id: str
    name: str
    artist: str
    current: str
    client_visible: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlaylistPlaybackResult:
    success: bool
    playlist_id: str
    name: str
    current: str
    client_visible: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CdpSession:
    def __init__(self, websocket_url: str, timeout: float) -> None:
        self.websocket_url = websocket_url
        self.timeout = timeout
        self.websocket: Any = None
        self.sequence = 0

    async def __aenter__(self) -> "CdpSession":
        try:
            self.websocket = await websockets.connect(
                self.websocket_url,
                open_timeout=self.timeout,
                close_timeout=self.timeout,
            )
        except Exception as exc:
            raise ClientNotReadyError(
                f"无法连接网易云控制通道: {exc}", code="cdp_connection_failed"
            ) from exc
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self.websocket is not None:
            await self.websocket.close()

    async def evaluate(self, expression: str) -> Any:
        self.sequence += 1
        request_id = self.sequence
        await self.websocket.send(
            json.dumps(
                {
                    "id": request_id,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expression,
                        "returnByValue": True,
                        "awaitPromise": True,
                    },
                }
            )
        )
        while True:
            try:
                raw = await asyncio.wait_for(self.websocket.recv(), self.timeout)
            except asyncio.TimeoutError as exc:
                raise ClientControlError(
                    "等待网易云客户端响应超时", code="cdp_response_timeout"
                ) from exc
            response = json.loads(raw)
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise ClientControlError(
                    response["error"].get("message", "客户端控制失败"),
                    code="cdp_protocol_error",
                )
            runtime = response.get("result", {})
            if runtime.get("exceptionDetails"):
                description = (
                    runtime.get("result", {}).get("description")
                    or runtime["exceptionDetails"].get("text")
                    or "客户端页面执行失败"
                )
                raise ClientControlError(description, code="cdp_javascript_error")
            result = runtime.get("result", {})
            if result.get("subtype") == "error":
                raise ClientControlError(
                    result.get("description", "客户端页面执行失败"),
                    code="cdp_javascript_error",
                )
            return result.get("value")


class NetEaseClientController:
    def __init__(self, config: ClientConfig | None = None) -> None:
        self.config = config or ClientConfig.from_env()

    def status(self) -> dict[str, Any]:
        target = self._get_debug_target()
        windows = self._client_windows()
        visible = [window for window in windows if _is_useful_visible_window(window)]
        return {
            "ready": bool(target and windows),
            "control_connected": bool(target),
            "on_input_desktop": bool(windows),
            "main_window_visible": bool(visible),
            "current_desktop": current_desktop_name(),
            "input_desktop": input_desktop_name(),
            "client_desktop": self.config.desktop_name,
            "windows": [
                {
                    "handle": window.handle,
                    "title": window.title,
                    "visible": window.visible,
                    "width": window.width,
                    "height": window.height,
                }
                for window in windows
            ],
        }

    def play_song(self, song_id: str | int, name: str, artist: str) -> dict[str, Any]:
        if sys.platform != "win32":
            raise ClientNotReadyError("新版客户端控制目前仅支持 Windows")
        target = self._ensure_debug_target()
        try:
            result = _run_coroutine_sync(
                lambda: self._play_song_async(
                    target["webSocketDebuggerUrl"], str(song_id), name, artist
                )
            )
        except ClientControlError:
            raise
        except Exception as exc:
            raise ClientControlError(f"网易云客户端控制失败: {exc}") from exc
        return result.to_dict()

    def play_playlist(
        self,
        playlist_id: str | int,
        name: str,
        first_song: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if sys.platform != "win32":
            raise ClientNotReadyError("新版客户端控制目前仅支持 Windows")
        target = self._ensure_debug_target()
        try:
            result = _run_coroutine_sync(
                lambda: self._play_playlist_async(
                    target["webSocketDebuggerUrl"], str(playlist_id), name, first_song
                )
            )
        except ClientControlError:
            raise
        except Exception as exc:
            raise ClientControlError(f"网易云歌单控制失败: {exc}") from exc
        return result.to_dict()

    def launch_visible_client(self) -> dict[str, Any]:
        if sys.platform != "win32":
            raise ClientNotReadyError("可见客户端启动器目前仅支持 Windows")
        active_desktop = current_desktop_name()
        if (active_desktop or "").casefold() != self.config.desktop_name.casefold():
            raise ClientNotReadyError(
                f"启动器当前位于不可见桌面 {active_desktop or '未知'}。请在文件资源管理器中"
                "双击“启动网易云音乐-MCP.cmd”，不要从 Codex 终端调用。",
                code="wrong_desktop",
            )

        target = self._get_debug_target()
        if target and self._client_windows():
            _run_coroutine_sync(
                lambda: self._show_existing_client(target["webSocketDebuggerUrl"])
            )
            return {"success": True, "already_running": True, **self.status()}

        client = self._find_client_executable()
        self._stop_existing_client()
        subprocess.Popen(
            [
                str(client),
                f"--remote-debugging-port={self.config.debug_port}",
                "--remote-allow-origins=*",
            ],
            cwd=str(client.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

        deadline = time.monotonic() + self.config.launch_timeout
        target = None
        while time.monotonic() < deadline:
            target = self._get_debug_target()
            if target and self._client_windows():
                _run_coroutine_sync(
                    lambda: self._show_existing_client(target["webSocketDebuggerUrl"])
                )
                if self._wait_for_visible_window(4.0):
                    return {"success": True, "already_running": False, **self.status()}
            time.sleep(0.4)

        if target:
            raise ClientNotReadyError(
                "网易云控制通道已建立，但主窗口未进入 Windows 可见桌面",
                code="client_not_on_input_desktop",
            )
        raise ClientNotReadyError(
            "网易云客户端未能建立控制通道", code="client_launch_failed"
        )

    def _get_debug_target(self) -> dict[str, Any] | None:
        try:
            with urllib.request.urlopen(
                self.config.debug_endpoint, timeout=self.config.request_timeout
            ) as response:
                targets = json.load(response)
        except (OSError, ValueError, urllib.error.URLError):
            return None
        candidates = [
            target
            for target in targets
            if target.get("webSocketDebuggerUrl")
            and target.get("url", "").startswith("orpheus://")
        ]
        return candidates[0] if candidates else None

    def _ensure_debug_target(self) -> dict[str, Any]:
        target = self._get_debug_target()
        windows = self._client_windows()
        if target and windows:
            return target

        if target:
            raise ClientNotReadyError(
                "检测到网易云控制通道，但官方窗口位于不可见桌面。请完全退出客户端，"
                "再从文件资源管理器双击“启动网易云音乐-MCP.cmd”。",
                code="client_on_hidden_desktop",
            )
        if windows:
            raise ClientNotReadyError(
                "网易云客户端已打开，但没有启用 MCP 控制通道。请完全退出客户端，"
                "再双击“启动网易云音乐-MCP.cmd”。",
                code="control_channel_missing",
            )

        # MCP can run in Codex's isolated desktop. Explicitly target Windows'
        # Default desktop so the official client is visible to the user.
        self._request_visible_launcher()
        deadline = time.monotonic() + self.config.launch_timeout
        while time.monotonic() < deadline:
            target = self._get_debug_target()
            windows = self._client_windows()
            if target and windows:
                return target
            time.sleep(0.35)

        raise ClientNotReadyError(
            "已请求在 Windows 可见桌面自动启动网易云，但客户端未在限定时间内就绪。"
            "请双击“启动网易云音乐-MCP.cmd”查看启动错误。",
            code="client_launch_failed",
        )

    def _request_visible_launcher(self) -> None:
        """Ask a helper on the user-visible desktop to start the official client."""
        if sys.platform != "win32":
            raise ClientNotReadyError("新版客户端控制目前仅支持 Windows")

        interpreter = Path(sys.executable)
        windowless_interpreter = interpreter.with_name("pythonw.exe")
        if windowless_interpreter.is_file():
            interpreter = windowless_interpreter
        try:
            launch_process_on_desktop(
                [
                    str(interpreter),
                    "-m",
                    "cloud_music_mcp.visible_client",
                    "--background",
                ],
                cwd=Path.cwd(),
                desktop_name=self.config.desktop_name,
            )
        except OSError as exc:
            raise ClientNotReadyError(
                f"无法在 Windows 可见桌面启动网易云: {exc}",
                code="visible_desktop_launch_failed",
            ) from exc

    def _find_client_executable(self) -> Path:
        override = os.getenv("CLOUD_MUSIC_CLIENT_PATH")
        if override:
            path = Path(override).expanduser()
            if path.is_file():
                return path
            raise ClientNotReadyError(
                f"CLOUD_MUSIC_CLIENT_PATH 指向的文件不存在: {path}",
                code="client_path_invalid",
            )
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT, r"orpheus\shell\open\command"
            ) as key:
                command = winreg.QueryValueEx(key, None)[0]
            match = re.match(
                r'^\s*"([^"]+cloudmusic\.exe)"|^\s*([^\s]+cloudmusic\.exe)',
                command,
                re.IGNORECASE,
            )
            if match:
                path = Path(match.group(1) or match.group(2))
                if path.is_file():
                    return path
        except (OSError, ImportError):
            pass
        candidates = [
            Path(os.getenv("PROGRAMFILES", "")) / "NetEase/CloudMusic/cloudmusic.exe",
            Path(os.getenv("PROGRAMFILES(X86)", ""))
            / "NetEase/CloudMusic/cloudmusic.exe",
            Path(os.getenv("LOCALAPPDATA", ""))
            / "NetEase/CloudMusic/cloudmusic.exe",
        ]
        for path in candidates:
            if path.is_file():
                return path
        raise ClientNotReadyError(
            "未找到网易云音乐官方客户端，请先安装最新版客户端",
            code="client_not_installed",
        )

    def _stop_existing_client(self) -> None:
        for image in ("cloudmusic.exe", "cloudmusic_reporter.exe"):
            subprocess.run(
                ["taskkill", "/IM", image, "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        time.sleep(0.8)

    def _client_windows(self) -> list[WindowInfo]:
        return find_windows_by_class(MAIN_WINDOW_CLASSES, self.config.desktop_name)

    def _visible_client_windows(self) -> list[WindowInfo]:
        return [window for window in self._client_windows() if _is_useful_visible_window(window)]

    def _wait_for_visible_window(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._visible_client_windows():
                return True
            time.sleep(0.2)
        return False

    async def _show_existing_client(self, websocket_url: str) -> None:
        async with CdpSession(websocket_url, self.config.request_timeout) as session:
            await self._show_when_ready(session)

    async def _show_when_ready(self, session: CdpSession) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + min(
            self.config.launch_timeout, 10.0
        )
        result: dict[str, Any] = {}
        while asyncio.get_running_loop().time() < deadline:
            result = await session.evaluate(_show_client_script()) or {}
            if result.get("ok"):
                return result
            if result.get("error_code") != "page_not_ready":
                break
            await asyncio.sleep(0.3)
        raise ClientControlError(
            result.get("error", "无法显示网易云客户端主窗口"),
            code=result.get("error_code", "show_window_failed"),
        )

    async def _play_song_async(
        self, websocket_url: str, song_id: str, name: str, artist: str
    ) -> PlaybackResult:
        async with CdpSession(websocket_url, self.config.request_timeout) as session:
            await self._show_when_ready(session)
            if not await asyncio.to_thread(self._wait_for_visible_window, 4.0):
                raise ClientNotReadyError(
                    "控制通道可用，但 Windows 可见桌面上没有官方主窗口",
                    code="main_window_not_visible",
                )

            state = await session.evaluate(_state_script(song_id, name, artist))
            if state.get("matches") and state.get("playing"):
                return self._verified_result(song_id, name, artist, state)

            search = await session.evaluate(_search_script(f"{name} {artist}"))
            if not search or not search.get("ok"):
                raise ClientControlError(
                    (search or {}).get("error", "客户端搜索框不可用"),
                    code="search_unavailable",
                )

            deadline = asyncio.get_running_loop().time() + self.config.search_timeout
            while asyncio.get_running_loop().time() < deadline:
                click_result = await session.evaluate(_click_script(song_id, name, artist))
                if click_result and click_result.get("ok"):
                    break
                await asyncio.sleep(0.35)
            else:
                raise ClientControlError(
                    f"客户端搜索结果中未找到《{name}》({song_id})",
                    code="song_not_found_in_client",
                )

            deadline = asyncio.get_running_loop().time() + self.config.playback_timeout
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.4)
                state = await session.evaluate(_state_script(song_id, name, artist))
                if state.get("matches") and state.get("playing"):
                    await session.evaluate(_show_client_script())
                    if not self._visible_client_windows():
                        raise PlaybackVerificationError(
                            "歌曲已播放，但官方主窗口没有出现在 Windows 可见桌面"
                        )
                    return self._verified_result(song_id, name, artist, state)
            raise PlaybackVerificationError(
                f"客户端未确认播放《{name}》；当前曲目: {state.get('current') or '未知'}"
            )

    def _verified_result(
        self, song_id: str, name: str, artist: str, state: dict[str, Any]
    ) -> PlaybackResult:
        if not self._visible_client_windows():
            raise PlaybackVerificationError("播放状态已改变，但官方主窗口不可见")
        return PlaybackResult(
            success=True,
            song_id=song_id,
            name=name,
            artist=artist,
            current=state.get("current", ""),
            client_visible=True,
        )

    async def _play_playlist_async(
        self,
        websocket_url: str,
        playlist_id: str,
        name: str,
        first_song: dict[str, Any] | None,
    ) -> PlaylistPlaybackResult:
        async with CdpSession(websocket_url, self.config.request_timeout) as session:
            await self._show_when_ready(session)
            if not await asyncio.to_thread(self._wait_for_visible_window, 4.0):
                raise ClientNotReadyError(
                    "控制通道可用，但 Windows 可见桌面上没有官方主窗口",
                    code="main_window_not_visible",
                )

            navigation = await session.evaluate(_navigate_to_playlist_script(playlist_id))
            if not navigation or not navigation.get("ok"):
                raise ClientControlError(
                    f"官方客户端侧边栏中未找到歌单《{name}》({playlist_id})",
                    code="playlist_not_available_in_client",
                )

            deadline = asyncio.get_running_loop().time() + self.config.search_timeout
            page_state: dict[str, Any] = {}
            while asyncio.get_running_loop().time() < deadline:
                page_state = await session.evaluate(_playlist_page_state_script(playlist_id, name))
                if page_state.get("matches"):
                    break
                await asyncio.sleep(0.3)
            else:
                raise ClientControlError(
                    f"客户端未能打开歌单《{name}》", code="playlist_navigation_failed"
                )

            played = await session.evaluate(_playlist_playall_script(playlist_id))
            if not played or not played.get("ok"):
                raise ClientControlError(
                    (played or {}).get("error", "未找到歌单的播放全部按钮"),
                    code="playlist_play_button_unavailable",
                )

            deadline = asyncio.get_running_loop().time() + self.config.playback_timeout
            state: dict[str, Any] = {}
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.4)
                state = await session.evaluate(
                    _playlist_playback_state_script(first_song)
                )
                if state.get("playing") and state.get("matches"):
                    await self._show_when_ready(session)
                    if not self._visible_client_windows():
                        raise PlaybackVerificationError(
                            "歌单已开始播放，但官方主窗口没有出现在 Windows 可见桌面"
                        )
                    return PlaylistPlaybackResult(
                        success=True,
                        playlist_id=playlist_id,
                        name=name,
                        current=state.get("current", ""),
                        client_visible=True,
                    )

            raise PlaybackVerificationError(
                f"客户端未确认播放歌单《{name}》；当前曲目: {state.get('current') or '未知'}"
            )


def play_song(song_id: str | int, name: str, artist: str) -> dict[str, Any]:
    return NetEaseClientController().play_song(song_id, name, artist)


def play_playlist(
    playlist_id: str | int,
    name: str,
    first_song: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return NetEaseClientController().play_playlist(playlist_id, name, first_song)


def launch_visible_client() -> dict[str, Any]:
    return NetEaseClientController().launch_visible_client()


def get_client_status() -> dict[str, Any]:
    return NetEaseClientController().status()


def _run_coroutine_sync(
    coroutine_factory: Callable[[], Coroutine[Any, Any, T]],
) -> T:
    """Run a coroutine from synchronous code, including FastMCP's event-loop thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine_factory())

    # FastMCP invokes synchronous tools from its own event-loop thread.  A nested
    # asyncio.run() is invalid there, so give this independent CDP operation its
    # own worker thread and event loop while preserving the synchronous API.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="cloud-music-cdp") as executor:
        return executor.submit(lambda: asyncio.run(coroutine_factory())).result()


def _is_useful_visible_window(window: WindowInfo) -> bool:
    return window.visible and window.width > 200 and window.height > 150


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ClientControlError(f"环境变量 {name} 必须是整数") from exc
    if not minimum <= value <= maximum:
        raise ClientControlError(f"环境变量 {name} 必须在 {minimum}..{maximum} 之间")
    return value


def _env_float(name: str, default: float, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ClientControlError(f"环境变量 {name} 必须是数字") from exc
    if value < minimum:
        raise ClientControlError(f"环境变量 {name} 不能小于 {minimum}")
    return value


def _search_script(keyword: str) -> str:
    value = json.dumps(keyword, ensure_ascii=False)
    return rf'''(() => {{
      const input = document.querySelector('[data-testid="tid_searchbox_input"]');
      if (!input) return {{ok:false, error:'未找到客户端搜索框'}};
      input.focus();
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, {value});
      input.dispatchEvent(new InputEvent('input', {{bubbles:true, inputType:'insertText', data:{value}}}));
      input.dispatchEvent(new Event('change', {{bubbles:true}}));
      for (const type of ['keydown', 'keypress', 'keyup']) {{
        input.dispatchEvent(new KeyboardEvent(type, {{key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true, cancelable:true}}));
      }}
      return {{ok:true}};
    }})()'''


def _click_script(song_id: str, name: str, artist: str) -> str:
    wanted_id = json.dumps(str(song_id))
    wanted_name = json.dumps(name, ensure_ascii=False)
    wanted_artist = json.dumps(artist, ensure_ascii=False)
    return rf'''(() => {{
      const norm = value => String(value || '').normalize('NFKC').toLowerCase()
        .replace(/[\s·・,，、/\\|&＆()（）\[\]【】'"“”‘’._-]+/g, '');
      const wantedId = {wanted_id};
      const wantedName = norm({wanted_name});
      const wantedArtists = String({wanted_artist}).split(/[\/&,，、]+/).map(norm).filter(Boolean);
      const cards = [...document.querySelectorAll('[data-testid="tid_cell_pc_common_songcard"]')];
      const readId = node => {{
        for (const item of [node, ...node.querySelectorAll('[data-log]')]) {{
          try {{
            const params = JSON.parse(item.getAttribute('data-log')).params || {{}};
            const id = params.s_songId || params.s_cid || params.songId || params.id;
            if (id != null) return String(id);
          }} catch (_) {{}}
        }}
        return '';
      }};
      let card = cards.find(node => readId(node) === wantedId);
      if (!card) {{
        card = cards.find(node => {{
          const text = norm(node.innerText);
          return text.includes(wantedName) && wantedArtists.every(item => text.includes(item));
        }});
      }}
      if (!card) return {{ok:false, count:cards.length}};
      const button = card.querySelector('[data-testid="tid_trackcard_play_btn"]');
      if (button) {{
        button.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true, view:window}}));
        return {{ok:true, matchedBy:readId(card) === wantedId ? 'id' : 'text'}};
      }}
      card.dispatchEvent(new MouseEvent('dblclick', {{bubbles:true, cancelable:true, view:window}}));
      return {{ok:true, matchedBy:'doubleClick'}};
    }})()'''


def _state_script(song_id: str, name: str, artist: str) -> str:
    wanted_id = json.dumps(str(song_id))
    wanted_name = json.dumps(name, ensure_ascii=False)
    wanted_artist = json.dumps(artist, ensure_ascii=False)
    return rf'''(() => {{
      const norm = value => String(value || '').normalize('NFKC').toLowerCase()
        .replace(/[\s·・,，、/\\|&＆()（）\[\]【】'"“”‘’._-]+/g, '');
      const info = [...document.querySelectorAll('[class*="songPlayInfo"]')]
        .map(node => node.innerText).filter(Boolean).join('\n');
      const button = document.querySelector('#btn_pc_minibar_play');
      let action = '';
      try {{ action = JSON.parse(button.getAttribute('data-log')).params.type || ''; }} catch (_) {{}}
      let currentId = '';
      for (const node of document.querySelectorAll('[class*="songPlayInfo"] [data-log], #btn_pc_minibar_play[data-log]')) {{
        try {{
          const params = JSON.parse(node.getAttribute('data-log')).params || {{}};
          const id = params.s_songId || params.s_cid || params.songId;
          if (id != null) {{ currentId = String(id); break; }}
        }} catch (_) {{}}
      }}
      const text = norm(info);
      const artists = String({wanted_artist}).split(/[\/&,，、]+/).map(norm).filter(Boolean);
      const textMatches = text.includes(norm({wanted_name})) && artists.every(item => text.includes(item));
      return {{
        matches: currentId ? currentId === {wanted_id} : textMatches,
        playing: action === 'pause' || !!(button && button.querySelector('[aria-label="pause"]')),
        current: info,
        currentId,
        action
      }};
    }})()'''


def _show_client_script() -> str:
    return r'''(async () => {
      const native = window.legacyNativeCmder;
      const search = document.querySelector('[data-testid="tid_searchbox_input"]');
      if (!native || !search) return {
        ok:false,
        error:'客户端页面尚未完成初始化',
        error_code:'page_not_ready',
        hasNative:!!native,
        hasSearch:!!search
      };
      await native.call('winhelper.showWindow', 'show');
      const status = await native.call('winhelper.getWindowInfo', 'status');
      if (status && (status.status === 'minimize' || status.status === 'hide')) {
        await native.call('winhelper.showWindow', 'restore');
      }
      return {ok:true, status};
    })()'''


def _navigate_to_playlist_script(playlist_id: str) -> str:
    wanted_id = json.dumps(str(playlist_id))
    return rf'''(() => {{
      const wanted = {wanted_id};
      const read = node => {{
        try {{ return JSON.parse(node.getAttribute('data-log')).params || {{}}; }} catch (_) {{ return {{}}; }}
      }};
      const item = [...document.querySelectorAll('[data-log]')].find(node => {{
        const params = read(node);
        return String(params.s_cid || params.s_playlistId || '') === wanted
          && (params.s_ctype === 'list' || params.s_playlistId != null);
      }});
      if (!item) return {{ok:false}};
      item.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true, view:window}}));
      return {{ok:true}};
    }})()'''


def _playlist_page_state_script(playlist_id: str, name: str) -> str:
    wanted_id = json.dumps(str(playlist_id))
    wanted_name = json.dumps(name, ensure_ascii=False)
    return rf'''(() => {{
      const wanted = {wanted_id};
      const pages = [...document.querySelectorAll('[data-log]')];
      const page = pages.find(node => {{
        try {{
          const log = JSON.parse(node.getAttribute('data-log'));
          const params = log.params || {{}};
          return log.oid === 'page_pc_songlist' && String(params.s_cid || '') === wanted;
        }} catch (_) {{ return false; }}
      }});
      const title = document.querySelector('[data-testid="tid_playlist_title"]')?.innerText || '';
      return {{
        matches: !!page && title.includes({wanted_name}),
        title,
        pageFound: !!page
      }};
    }})()'''


def _playlist_playall_script(playlist_id: str) -> str:
    wanted_id = json.dumps(str(playlist_id))
    return rf'''(() => {{
      const wanted = {wanted_id};
      const button = document.querySelector('[data-testid="tid_playlist_playall_btn"]');
      if (!button) return {{ok:false, error:'未找到播放全部按钮'}};
      try {{
        const params = JSON.parse(button.getAttribute('data-log')).params || {{}};
        if (String(params.s_playlistId || '') !== wanted) {{
          return {{ok:false, error:'播放按钮不属于目标歌单'}};
        }}
      }} catch (_) {{ return {{ok:false, error:'无法验证播放全部按钮'}}; }}
      button.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true, view:window}}));
      return {{ok:true}};
    }})()'''


def _playlist_playback_state_script(first_song: dict[str, Any] | None) -> str:
    if first_song:
        return _state_script(
            str(first_song["id"]), first_song["name"], first_song["artist"]
        )
    return r'''(() => {
      const info = [...document.querySelectorAll('[class*="songPlayInfo"]')]
        .map(node => node.innerText).filter(Boolean).join('\n');
      const button = document.querySelector('#btn_pc_minibar_play');
      let action = '';
      try { action = JSON.parse(button.getAttribute('data-log')).params.type || ''; } catch (_) {}
      return {
        matches: !!info,
        playing: action === 'pause' || !!(button && button.querySelector('[aria-label="pause"]')),
        current: info
      };
    })()'''
