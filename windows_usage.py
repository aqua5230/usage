"""Windows entry point — run with: pythonw windows_usage.py [--mock] [--interval N]"""
from __future__ import annotations

import argparse
import logging
import os
import sys


def _setup_logging() -> None:
    level = logging.DEBUG if os.environ.get("USAGE_DEBUG") == "1" else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Claude Code 用量 Windows 小工具")
    parser.add_argument("--mock", action="store_true", help="使用假資料預覽介面")
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="輪詢秒數，預設 60，最小 30",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="安裝 statusLine hook 到 Claude Code",
    )
    parser.add_argument(
        "--unsetup",
        action="store_true",
        help="從 Claude Code 移除 statusLine hook",
    )
    args = parser.parse_args()
    args.interval = max(30, args.interval)
    return args


def _ensure_hook() -> None:
    """Auto-install statusLine hook if not already configured; show dialog with result."""
    import tkinter
    import tkinter.messagebox

    from setup_hook import (  # noqa: PLC2701  (private but same-package)
        _is_usage_hook,
        _load_settings,
        setup,
    )

    settings = _load_settings()
    if _is_usage_hook(settings.get("statusLine")):
        return

    ret = setup()
    root = tkinter.Tk()
    root.withdraw()
    if ret == 0:
        tkinter.messagebox.showinfo(
            "statusLine Hook 已安裝",
            "請重新啟動 Claude Code 以啟用用量追蹤。",
        )
    else:
        tkinter.messagebox.showerror(
            "安裝失敗",
            "statusLine hook 安裝失敗，請手動執行：\n\n"
            "  python windows_usage.py --setup",
        )
    root.destroy()


def main() -> None:
    if sys.platform != "win32":
        sys.exit("windows_usage.py is Windows-only. On macOS/Linux run: python3 main.py")

    _setup_logging()
    args = parse_args()

    if args.setup:
        from setup_hook import setup
        raise SystemExit(setup())

    if args.unsetup:
        from setup_hook import unsetup
        raise SystemExit(unsetup())

    _ensure_hook()

    import windows_widget
    windows_widget.run(mock=args.mock, interval=args.interval)


if __name__ == "__main__":
    main()
