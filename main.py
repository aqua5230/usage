from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from contextlib import suppress

from rich.console import Console
from rich.live import Live

import menubar
from tui import AppViewState, render_screen
from usage_client import ClaudeUsageClient, PollOutcome, PollState
from usage_rate import UsageRateTracker

SPRITE_INTERVAL_S = [2.0, 0.8, 0.4, 0.15]  # idle/normal/active/heavy


def _setup_logging() -> None:
    level = logging.DEBUG if os.environ.get("USAGE_DEBUG") == "1" else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


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
    state: AppViewState,
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


def _apply_outcome(state: AppViewState, outcome: PollOutcome) -> None:
    state.poll_state = outcome.state
    if outcome.snapshot is not None:
        state.snapshot = outcome.snapshot
    if outcome.message:
        state.message = outcome.message
    if outcome.state == PollState.SUCCESS:
        state.fatal_message = None


async def run_tui(mock: bool, interval: int, force_group: int | None = None) -> None:
    console = Console()
    state = AppViewState()
    tracker = UsageRateTracker(forced_group=force_group, mock=mock)
    stop_event = asyncio.Event()
    client = ClaudeUsageClient(interval_seconds=interval, mock=mock)

    try:
        first_outcome = await client.fetch_once()
        _apply_outcome(state, first_outcome)

        poll_task = asyncio.create_task(poll_usage(client, state, stop_event))

        with Live(
            render_screen(state, 0),
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

                live.update(render_screen(state, frame_index), refresh=True)
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
    if args.tui:
        with suppress(KeyboardInterrupt):
            asyncio.run(
                run_tui(mock=args.mock, interval=args.interval, force_group=args.force_group)
            )
    else:
        menubar.run_app(mock=args.mock, interval=args.interval)


if __name__ == "__main__":
    main()
