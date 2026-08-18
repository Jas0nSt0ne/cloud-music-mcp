"""User-launched entry point for starting Cloud Music on the visible desktop."""

from __future__ import annotations

import argparse
import json

from .client_control import ClientControlError, get_client_status, launch_visible_client


def main() -> None:
    parser = argparse.ArgumentParser(description="在 Windows 可见桌面启动网易云官方客户端")
    parser.add_argument("--status", action="store_true", help="只检查状态，不启动客户端")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--background", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    try:
        result = get_client_status() if args.status else launch_visible_client()
    except ClientControlError as exc:
        if args.json:
            print(
                json.dumps(
                    {"success": False, "error": str(exc), "error_code": exc.code},
                    ensure_ascii=False,
                )
            )
        elif not args.background:
            print(f"启动失败: {exc}")
        raise SystemExit(1) from exc

    if args.background:
        return
    if args.json or args.status:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if result.get("already_running"):
        print("网易云音乐官方客户端已在可见桌面运行，可以使用 MCP 播放。")
    else:
        print("网易云音乐官方客户端已在可见桌面启动，可以使用 MCP 播放。")


if __name__ == "__main__":
    main()
