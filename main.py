# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import os
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

# Inside usage.app this file sits in Contents/Resources/ next to py2app's
# __boot__.py, while the modules it imports live in lib/python313.zip. Running
# it with an outside interpreter therefore fails on the first local import with
# a confusing ImportError (a PyPI package named `i18n` even shadows ours). Bail
# out with instructions instead. py2app's own launcher sets RESOURCEPATH.  (#92)
if not os.environ.get("RESOURCEPATH") and (Path(__file__).parent / "__boot__.py").exists():
    sys.exit(
        "This main.py is part of the usage.app bundle and cannot be run directly.\n"
        'To install the status line, open usage from the menu bar and click "Set Up Status Line".\n'
        "To run from source instead: https://github.com/aqua5230/usage"
    )

from loaders.claude_usage import ClaudeUsageClient, PollOutcome, PollState
from quota.usage_rate import UsageRateTracker
from usage_common import prefs
from usage_common.i18n import t as _t
from usage_common.prefs import PREFERENCES_FILE as PREFERENCES_FILE

SPRITE_INTERVAL_S = [2.0, 0.8, 0.4, 0.15]  # idle/normal/active/heavy
IMPORT_RETRY_ATTEMPTS = 6
IMPORT_RETRY_DELAY_S = 3.0

logger = logging.getLogger(__name__)


def _load_preferences() -> dict[str, Any]:
    return prefs._load_preferences(PREFERENCES_FILE)


def _save_preferences(data: dict[str, Any]) -> None:
    prefs._save_preferences(data, PREFERENCES_FILE)


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
    import usage_common.usage_logging as usage_logging

    usage_logging.setup_logging()


def _self_heal() -> None:
    try:
        from installer import session_hooks

        session_hooks.self_heal()
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("self-heal failed", exc_info=True)

    try:
        from usage_common.usage_dir_sweeper import sweep_stale_temp_files

        sweep_stale_temp_files()
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("stale temp file sweep failed", exc_info=True)


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
    parser.add_argument(
        "--doctor",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=argparse.SUPPRESS,
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
    tui = _import_module_with_oserror_retry("tui.app")
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
    if sys.argv[1:2] == ["status"]:
        from usage_app import cli as usage_cli

        usage_cli.main()
        return
    _setup_logging()
    args = parse_args()
    if args.doctor:
        from usage_app import doctor

        report = doctor.collect()
        output = doctor.render_json(report) if args.json else doctor.render(report)
        print(output, end="")
        raise SystemExit(doctor.exit_code(report))
    if args.setup:
        from installer import session_hooks
        from installer.setup_hook import setup

        exit_code = setup()
        if exit_code == 0:
            session_hooks._migrate_bundled_python_commands_if_needed()
        raise SystemExit(exit_code)
    if args.unsetup:
        from installer.session_hooks import disable_session_resume, disable_terse_mode
        from installer.setup_hook import unsetup

        disable_session_resume()
        disable_terse_mode()
        raise SystemExit(unsetup())
    preferences_snapshot = _load_preferences()
    _self_heal()
    if args.tui:
        with suppress(KeyboardInterrupt):
            asyncio.run(
                run_tui(mock=args.mock, interval=args.interval, force_group=args.force_group)
            )
    elif sys.platform == "darwin":
        menubar = _import_module_with_oserror_retry("menubar.app")
        menubar.show_forwarder_mode_prompt_if_needed()
        menubar.run_app(
            mock=args.mock, interval=args.interval, preferences_snapshot=preferences_snapshot
        )
    elif sys.platform == "win32":
        try:
            wintray = importlib.import_module("wintray.app")
        except ModuleNotFoundError as exc:
            # Any missing module — wintray itself, an optional GUI package, or a
            # transitive import — must degrade to the TUI; a bare raise would exit
            # a --windowed build with no visible output at all.
            print(f"{_t('wintray_unavailable')} [{exc.name}]")
            with suppress(KeyboardInterrupt):
                asyncio.run(
                    run_tui(mock=args.mock, interval=args.interval, force_group=args.force_group)
                )
        else:
            try:
                wintray.run_app(
                    mock=args.mock,
                    interval=args.interval,
                    preferences_snapshot=preferences_snapshot,
                )
            except ModuleNotFoundError as exc:
                print(f"{_t('wintray_unavailable')} [{exc.name}]")
                with suppress(KeyboardInterrupt):
                    asyncio.run(
                        run_tui(
                            mock=args.mock,
                            interval=args.interval,
                            force_group=args.force_group,
                        )
                    )
    else:
        with suppress(KeyboardInterrupt):
            asyncio.run(
                run_tui(mock=args.mock, interval=args.interval, force_group=args.force_group)
            )


if __name__ == "__main__":
    main()
