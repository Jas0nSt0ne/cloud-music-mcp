"""Authentication persistence and QR-code login."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import qrcode
from pyncm import GetCurrentSession, apis

from .windows_desktop import current_desktop_name, input_desktop_name


PACKAGE_DIR = Path(__file__).resolve().parent
LEGACY_COOKIE_FILE = PACKAGE_DIR / "storage" / "cookies.json"


def get_storage_dir() -> Path:
    override = os.getenv("CLOUD_MUSIC_MCP_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32" and os.getenv("APPDATA"):
        return Path(os.environ["APPDATA"]) / "cloud-music-mcp"
    return Path.home() / ".cloud-music-mcp"


def ensure_storage_dir() -> Path:
    directory = get_storage_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Sandboxed MCP hosts may only grant writes beside the checked-out project.
        directory = LEGACY_COOKIE_FILE.parent
        directory.mkdir(parents=True, exist_ok=True)
    cookie_file = directory / "cookies.json"
    if not cookie_file.exists() and LEGACY_COOKIE_FILE.is_file():
        shutil.copy2(LEGACY_COOKIE_FILE, cookie_file)
    return directory


def get_cookie_file() -> Path:
    return ensure_storage_dir() / "cookies.json"


def load_session(*, verify: bool = True) -> tuple[bool, str | None]:
    cookie_file = get_cookie_file()
    if not cookie_file.is_file():
        return False, None
    try:
        with cookie_file.open("r", encoding="utf-8") as stream:
            cookies = json.load(stream)
        if not isinstance(cookies, dict):
            return False, None
        GetCurrentSession().cookies.update(cookies)
        if not verify:
            return True, None
        user_info = apis.login.GetCurrentLoginStatus()
        profile = user_info.get("profile") if user_info.get("code") == 200 else None
        return (True, profile.get("nickname")) if profile else (False, None)
    except (OSError, ValueError, TypeError):
        return False, None


def save_session() -> bool:
    try:
        cookies = GetCurrentSession().cookies.get_dict()
        with get_cookie_file().open("w", encoding="utf-8") as stream:
            json.dump(cookies, stream, ensure_ascii=False, indent=2)
        return True
    except (OSError, TypeError):
        return False


def check_login_status() -> dict[str, Any]:
    logged_in, nickname = load_session()
    return {"logged_in": logged_in, "nickname": nickname}


def login_via_qrcode() -> dict[str, Any]:
    """Legacy blocking QR login with desktop-aware image opening."""
    try:
        result = apis.login.LoginQrcodeUnikey(1)
        if result.get("code") != 200 or not result.get("unikey"):
            return {"success": False, "message": "获取二维码失败"}

        key = result["unikey"]
        qr_content = f"https://music.163.com/login?codekey={key}"
        image = qrcode.make(qr_content)
        qr_path = ensure_storage_dir() / "login_qrcode.png"
        image.save(qr_path)
        opened = _open_qr_if_visible(qr_path)

        for _ in range(60):
            result = apis.login.LoginQrcodeCheck(key)
            code = result.get("code")
            if code == 800:
                return {
                    "success": False,
                    "message": "二维码已过期，请重试",
                    "qr_path": str(qr_path),
                }
            if code == 803:
                if result.get("cookie"):
                    apis.login.WriteLoginInfo(result["cookie"])
                if not save_session():
                    return {"success": False, "message": "登录成功，但保存 Cookie 失败"}
                status = check_login_status()
                nickname = status.get("nickname") or "用户"
                return {
                    "success": True,
                    "message": f"登录成功！欢迎回来，{nickname}",
                    "nickname": nickname,
                }
            time.sleep(2)
        return {
            "success": False,
            "message": "登录超时",
            "qr_path": str(qr_path),
            "qr_opened": opened,
        }
    except Exception as exc:
        return {"success": False, "message": f"错误: {exc}"}


def _open_qr_if_visible(path: Path) -> bool:
    try:
        if sys.platform == "win32":
            if current_desktop_name() != input_desktop_name():
                return False
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except OSError:
        return False
