"""Inspect Windows desktops and their top-level windows."""

from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass
from os import PathLike


DESKTOP_READOBJECTS = 0x0001
UOI_NAME = 2
CREATE_UNICODE_ENVIRONMENT = 0x00000400


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


@dataclass(frozen=True, slots=True)
class WindowInfo:
    handle: int
    process_id: int
    class_name: str
    title: str
    visible: bool
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def current_desktop_name() -> str | None:
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    return _user_object_name(user32.GetThreadDesktop(kernel32.GetCurrentThreadId()))


def input_desktop_name() -> str | None:
    if sys.platform != "win32":
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    handle = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
    if not handle:
        return None
    try:
        return _user_object_name(handle)
    finally:
        user32.CloseDesktop(handle)


def list_desktop_windows(desktop_name: str = "Default") -> list[WindowInfo]:
    if sys.platform != "win32":
        return []
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenDesktopW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    user32.OpenDesktopW.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    desktop = user32.OpenDesktopW(desktop_name, 0, False, DESKTOP_READOBJECTS)
    if not desktop:
        return []

    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    windows: list[WindowInfo] = []

    def collect(hwnd: int, _lparam: int) -> bool:
        title = ctypes.create_unicode_buffer(512)
        class_name = ctypes.create_unicode_buffer(256)
        process_id = wintypes.DWORD()
        rect = wintypes.RECT()
        user32.GetWindowTextW(hwnd, title, len(title))
        user32.GetClassNameW(hwnd, class_name, len(class_name))
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        windows.append(
            WindowInfo(
                handle=int(hwnd),
                process_id=int(process_id.value),
                class_name=class_name.value,
                title=title.value,
                visible=bool(user32.IsWindowVisible(hwnd)),
                left=rect.left,
                top=rect.top,
                right=rect.right,
                bottom=rect.bottom,
            )
        )
        return True

    callback = callback_type(collect)
    try:
        user32.EnumDesktopWindows(desktop, callback, 0)
    finally:
        user32.CloseDesktop(desktop)
    return windows


def find_windows_by_class(
    class_names: set[str] | frozenset[str], desktop_name: str = "Default"
) -> list[WindowInfo]:
    return [
        window
        for window in list_desktop_windows(desktop_name)
        if window.class_name in class_names
    ]


def launch_process_on_desktop(
    command: list[str], *, cwd: str | PathLike[str], desktop_name: str = "Default"
) -> int:
    """Create a GUI process directly in WinSta0's named desktop."""
    if sys.platform != "win32":
        raise OSError("仅 Windows 支持在指定桌面启动进程")
    if not command:
        raise ValueError("启动命令不能为空")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfo),
        ctypes.POINTER(_ProcessInformation),
    ]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    startup = _StartupInfo()
    startup.cb = ctypes.sizeof(startup)
    startup.lpDesktop = f"WinSta0\\{desktop_name}"
    process = _ProcessInformation()
    command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
    ok = kernel32.CreateProcessW(
        command[0],
        command_line,
        None,
        None,
        False,
        CREATE_UNICODE_ENVIRONMENT,
        None,
        str(cwd),
        ctypes.byref(startup),
        ctypes.byref(process),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    kernel32.CloseHandle(process.hThread)
    kernel32.CloseHandle(process.hProcess)
    return int(process.dwProcessId)


def _user_object_name(handle: int) -> str | None:
    if not handle:
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    needed = wintypes.DWORD()
    buffer = ctypes.create_unicode_buffer(256)
    ok = user32.GetUserObjectInformationW(
        handle,
        UOI_NAME,
        buffer,
        ctypes.sizeof(buffer),
        ctypes.byref(needed),
    )
    return buffer.value if ok else None
