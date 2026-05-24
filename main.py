from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import os
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from i18n import packaged_resource_path
from usage_client import ClaudeUsageClient, PollOutcome, PollState
from usage_lang import detect_lang
from usage_rate import UsageRateTracker

SPRITE_INTERVAL_S = [2.0, 0.8, 0.4, 0.15]  # idle/normal/active/heavy
IMPORT_RETRY_ATTEMPTS = 6
IMPORT_RETRY_DELAY_S = 3.0
PREFERENCES_FILE = Path(os.path.expanduser("~/.claude/usage-preferences.json"))
REPAIR_DISMISS_SECONDS = 24 * 3600

logger = logging.getLogger(__name__)


def _load_rich() -> tuple[type[Any], type[Any]]:
    rich_console = _import_module_with_oserror_retry("rich.console")
    rich_live = _import_module_with_oserror_retry("rich.live")
    return rich_console.Console, rich_live.Live


def _import_module_with_oserror_retry(name: str) -> Any:
    """Retry imports that can transiently fail under launchd with Errno 11."""
    for attempt in range(IMPORT_RETRY_ATTEMPTS):
        try:
            return importlib.import_module(name)
        except OSError:
            if attempt >= IMPORT_RETRY_ATTEMPTS - 1:
                raise
            logger.warning("import failed for %s, retrying", name, exc_info=True)
            time.sleep(IMPORT_RETRY_DELAY_S)
    raise RuntimeError("unreachable")


def _setup_logging() -> None:
    level = logging.DEBUG if os.environ.get("USAGE_DEBUG") == "1" else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _i18n_text(language: str, key: str) -> str:
    try:
        i18n_path = packaged_resource_path(
            "i18n.json", Path(__file__).with_name("i18n.json")
        )
        data = json.loads(i18n_path.read_text(encoding="utf-8"))
        table = data.get(language) or data.get("en") or {}
        return str(table.get(key) or data.get("en", {}).get(key) or key)
    except (OSError, json.JSONDecodeError, AttributeError):
        return key


def _health_language() -> str:
    return detect_lang()


def _load_preferences() -> dict[str, Any]:
    if not PREFERENCES_FILE.exists():
        return {}
    try:
        data = json.loads(PREFERENCES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_preferences(data: dict[str, Any]) -> None:
    PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PREFERENCES_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _save_user_preference(key: str) -> None:
    prefs = _load_preferences()
    if key == "repair_dismissed_at":
        prefs[key] = time.time()
    else:
        prefs[key] = True
    _save_preferences(prefs)


def _user_dismissed_repair_today() -> bool:
    prefs = _load_preferences()
    if prefs.get("no_auto_repair") is True:
        return True
    dismissed_at = prefs.get("repair_dismissed_at")
    if isinstance(dismissed_at, int | float):
        return (time.time() - float(dismissed_at)) < REPAIR_DISMISS_SECONDS
    return False


def _is_our_hook_in_settings() -> bool:
    try:
        import setup_hook

        return setup_hook._detect_current_state() in {"us-direct", "us-forwarder"}
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("hook health check failed", exc_info=True)
        return True


def _is_first_run() -> bool:
    try:
        import setup_hook
        import usage_client

        return not setup_hook.HOOK_TARGET.exists() and not Path(usage_client.STATUS_FILE).exists()
    except Exception:
        return True


def _show_repair_dialog() -> str:
    language = _health_language()
    title = _i18n_text(language, "repair_dialog_title")
    message = _i18n_text(language, "repair_dialog_message")
    repair = _i18n_text(language, "repair_dialog_repair")
    skip = _i18n_text(language, "repair_dialog_skip")
    never = _i18n_text(language, "repair_dialog_never")

    try:
        appkit = importlib.import_module("AppKit")
        alert = appkit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_(repair)
        alert.addButtonWithTitle_(skip)
        alert.addButtonWithTitle_(never)
        result = int(alert.runModal())
    except Exception:
        print(f"{title}: {message}")
        return "skip"

    if result == 1000:
        return "repair"
    if result == 1002:
        return "never"
    return "skip"


def health_check() -> None:
    if _is_our_hook_in_settings():
        return
    if _is_first_run():
        return
    if _user_dismissed_repair_today():
        return

    choice = _show_repair_dialog()
    if choice == "repair":
        import setup_hook

        setup_hook.setup(force_forwarder=True)
    elif choice == "never":
        _save_user_preference("no_auto_repair")
    else:
        _save_user_preference("repair_dismissed_at")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="顯示 Claude Code 用量的工具")
    parser.add_argument("--mock", action="store_true", help="使用假資料預覽介面")
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="輪詢秒數，預設 60，最小 30",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="使用舊版終端機 TUI 介面",
    )
    parser.add_argument(
        "--force-group",
        type=int,
        choices=[0, 1, 2, 3],
        default=None,
        help="強制使用某速率組（測試用，僅 TUI 模式有效），0=Idle 1=Normal 2=Active 3=Heavy",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="安裝 statusLine hook 到 Claude Code（首次使用必跑）",
    )
    parser.add_argument(
        "--unsetup",
        action="store_true",
        help="從 Claude Code 移除 statusLine hook 並還原原設定",
    )
    args = parser.parse_args()
    args.interval = max(30, args.interval)
    return args


async def poll_usage(
    client: ClaudeUsageClient,
    state: Any,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=client.interval_seconds)
            return
        except TimeoutError:
            pass

        state.poll_state = PollState.LOADING
        outcome = await client.fetch_once()
        _apply_outcome(state, outcome)


def _apply_outcome(state: Any, outcome: PollOutcome) -> None:
    state.poll_state = outcome.state
    if outcome.snapshot is not None:
        state.snapshot = outcome.snapshot
    if outcome.message:
        state.message = outcome.message
    if outcome.state == PollState.SUCCESS:
        state.fatal_message = None


async def run_tui(mock: bool, interval: int, force_group: int | None = None) -> None:
    tui = _import_module_with_oserror_retry("tui")
    Console, Live = _load_rich()
    console = Console()
    state = tui.AppViewState()
    tracker = UsageRateTracker(forced_group=force_group, mock=mock)
    stop_event = asyncio.Event()
    client = ClaudeUsageClient(interval_seconds=interval, mock=mock)

    try:
        first_outcome = await client.fetch_once()
        _apply_outcome(state, first_outcome)

        poll_task = asyncio.create_task(poll_usage(client, state, stop_event))

        with Live(
            tui.render_screen(state, 0),
            console=console,
            screen=True,
            refresh_per_second=10,
            transient=False,
        ) as live:
            start_time = time.monotonic()
            while not stop_event.is_set():
                now = time.monotonic()

                effective_group = tracker.group()
                state.rate_group = effective_group

                interval_s = SPRITE_INTERVAL_S[effective_group]
                frame_index = int((now - start_time) / interval_s) % 4

                live.update(tui.render_screen(state, frame_index), refresh=True)
                await asyncio.sleep(0.1)

        await poll_task
    finally:
        stop_event.set()
        await client.aclose()


def main() -> None:
    _setup_logging()
    args = parse_args()
    if args.setup:
        from setup_hook import setup

        raise SystemExit(setup())
    if args.unsetup:
        from setup_hook import unsetup

        raise SystemExit(unsetup())
    health_check()
    if args.tui:
        with suppress(KeyboardInterrupt):
            asyncio.run(
                run_tui(mock=args.mock, interval=args.interval, force_group=args.force_group)
            )
    else:
        menubar = _import_module_with_oserror_retry("menubar")
        menubar.run_app(mock=args.mock, interval=args.interval)


if __name__ == "__main__":
    main()
