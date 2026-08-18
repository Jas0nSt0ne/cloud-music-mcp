"""网易云音乐 MCP Server"""

import argparse
import logging
import sys

logging.getLogger("cloud_music_mcp").addHandler(logging.NullHandler())

from .main import mcp


def main():
    """MCP Server CLI 入口"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="网易云音乐 MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport type (default: stdio)",
    )

    args = parser.parse_args()

    mcp.run(transport=args.transport, show_banner=False)


if __name__ == "__main__":
    main()
