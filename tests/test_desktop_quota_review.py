from __future__ import annotations

import asyncio
import builtins
import io
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from adapters import rate_limits
from loaders import chromium_cache, claude_desktop
from loaders import claude_usage as usage_client
from menubar import state
from quota import status_payload
from tests.test_chromium_cache import Response, _cache
from tui import app as tui

NOW = 2_000_000_000.0


@pytest.fixture
def sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for module in (usage_client, rate_limits):
        for name in ("STATUS_FILE", "LEGACY_STATUS_FILE", "TT_STATUS_FILE"):
            monkeypatch.setattr(module, name, str(tmp_path / name))
    monkeypatch.setattr(usage_client, "_claude_json_file", lambda: str(tmp_path / "cli.json"))
    monkeypatch.setattr("loaders.claude_usage.time.time", lambda: NOW)
    monkeypatch.setenv("USAGE_LANG", "en")
    path = tmp_path / claude_desktop.HISTORY_NAME
    monkeypatch.setattr(claude_desktop, "desktop_history_paths", lambda: (path,))
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "samples": [{"t": (NOW - 120) * 1000, "org": "a", "u": {"fh": 54, "sd": 67}}],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.parametrize("five,seven", [(-1, 100), (100, -1), (-1, -1), (0, 0)])
def test_reset_is_normalized_for_loader_gui_tui_and_json(
    sources: Path, five: int, seven: int
) -> None:
    _cache(
        sources / "Cache/Cache_Data",
        Response(
            fetched=NOW - 120,
            url=b"https://claude.ai/api/organizations/a/usage",
            payload={
                "five_hour": {"utilization": 54, "resets_at": _iso(NOW + five)},
                "seven_day": {"utilization": 67, "resets_at": _iso(NOW + seven)},
            },
        ),
    )
    expected = (0 if five <= 0 else 54, 0 if seven <= 0 else 67)
    quota = claude_desktop.load_desktop_quota(NOW)
    assert quota is not None
    assert (quota.current_percent, quota.weekly_percent) == expected
    outcome = asyncio.run(usage_client.ClaudeUsageClient().fetch_once())
    snapshot = outcome.snapshot
    assert snapshot is not None
    assert (snapshot.current_percent, snapshot.weekly_percent) == expected
    cli = rate_limits.load_rate_limits()
    assert cli is not None
    payload = status_payload._status_agent(cli, int(NOW))
    for name, percent, reset in zip(
        ("five_hour", "seven_day"), expected, (five, seven), strict=True
    ):
        assert payload[name]["used_percent"] == percent
        assert payload[name]["resets_in_seconds"] == max(0, reset)
        row = state._quota_row("Session", percent, NOW + reset, NOW, state.CLAUDE_COLOR, "en")
        assert row.percent == percent
    output = io.StringIO()
    Console(file=output, width=120, color_system=None).print(
        tui.render_screen(tui.AppViewState(language="en", snapshot=snapshot), 0)
    )
    if five <= 0:
        assert "54%" not in output.getvalue()
    if seven <= 0:
        assert "67%" not in output.getvalue()


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def _code_cache(path: Path, *, account_matches: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "oauthAccount": {"accountUuid": "code-account"},
                "cachedUsageUtilization": {
                    "accountUuid": "code-account" if account_matches else "previous-account",
                    "fetchedAtMs": NOW * 1000,
                    "utilization": {
                        "five_hour": {"utilization": 22, "resets_at": _iso(NOW + 100)},
                        "seven_day": {"utilization": 33, "resets_at": _iso(NOW + 200)},
                    },
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("with_code_cache", [False, True])
def test_complete_hook_never_reads_desktop_even_on_repeated_polls(
    sources: Path, monkeypatch: pytest.MonkeyPatch, with_code_cache: bool
) -> None:
    Path(usage_client.STATUS_FILE).write_text(
        json.dumps(
            {
                "rate_limits": {
                    "five_hour": {"used_percentage": 12},
                    "seven_day": {"used_percentage": 13},
                }
            }
        ),
        encoding="utf-8",
    )
    if with_code_cache:
        _code_cache(sources / "cli.json")

    def forbidden(*args: Any) -> Any:
        pytest.fail("A complete hook must not read Desktop or the fallback cache")

    monkeypatch.setattr(claude_desktop, "load_desktop_quota", forbidden)
    monkeypatch.setattr(usage_client, "_read_claude_json_snapshot", forbidden)
    client = usage_client.ClaudeUsageClient()
    for _ in range(2):
        snapshot = asyncio.run(client.fetch_once()).snapshot
        assert snapshot is not None and snapshot.data_source == "hook"
        assert (snapshot.current_percent, snapshot.weekly_percent) == (12, 13)
        cli = rate_limits.load_rate_limits()
        assert cli is not None and (cli.five_hour_pct, cli.seven_day_pct) == (12, 13)


@pytest.mark.parametrize("hook", [None, {}, {"five_hour": {"used_percentage": 99}}])
def test_gui_and_cli_use_code_cache_before_desktop(
    sources: Path, monkeypatch: pytest.MonkeyPatch, hook: dict[str, Any] | None
) -> None:
    _code_cache(sources / "cli.json")
    if hook is not None:
        Path(usage_client.STATUS_FILE).write_text(
            json.dumps({"rate_limits": hook}), encoding="utf-8"
        )

    def forbidden(*args: Any) -> Any:
        pytest.fail("A valid Claude Code cache must not read Desktop")

    monkeypatch.setattr(claude_desktop, "load_desktop_quota", forbidden)
    client = usage_client.ClaudeUsageClient()
    for now, expected in [(NOW, (22, 33)), (NOW + 101, (0, 33)), (NOW + 201, (0, 0))]:
        monkeypatch.setattr("loaders.claude_usage.time.time", lambda now=now: now)
        snapshot = asyncio.run(client.fetch_once()).snapshot
        assert snapshot is not None and snapshot.data_source == "claude-json"
        assert (snapshot.current_percent, snapshot.weekly_percent) == expected
        cli = rate_limits.load_rate_limits()
        assert cli is not None and (cli.five_hour_pct, cli.seven_day_pct) == expected


def test_switched_code_account_falls_back_to_desktop_for_gui_and_cli(sources: Path) -> None:
    _code_cache(sources / "cli.json", account_matches=False)
    snapshot = asyncio.run(usage_client.ClaudeUsageClient().fetch_once()).snapshot
    assert snapshot is not None and snapshot.data_source == "claude-desktop"
    cli = rate_limits.load_rate_limits()
    assert cli is not None and (cli.five_hour_pct, cli.seven_day_pct) == (54, 67)


@pytest.mark.parametrize("org", ["\ud800", "\udfff", "org-\ud800"])
def test_invalid_latest_org_returns_no_data_without_reviving_old_account(
    sources: Path, org: str
) -> None:
    path = sources / claude_desktop.HISTORY_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    data["samples"].append({"t": NOW * 1000, "org": org, "u": {"fh": 90}})
    path.write_text(json.dumps(data), encoding="utf-8")
    assert claude_desktop.load_desktop_quota(NOW) is None
    assert asyncio.run(usage_client.ClaudeUsageClient().fetch_once()).snapshot is None
    assert rate_limits.load_rate_limits() is None


@pytest.mark.parametrize("encoding", ["zstd", "gzip", "deflate", "identity"])
def test_missing_decoder_only_disables_zstd_resets(
    sources: Path, monkeypatch: pytest.MonkeyPatch, encoding: str
) -> None:
    _cache(
        sources / "Cache/Cache_Data",
        Response(
            fetched=NOW - 120,
            url=b"https://claude.ai/api/organizations/a/usage",
            encoding=encoding,
            payload={"five_hour": {"utilization": 54, "resets_at": _iso(NOW + 100)}},
        ),
    )
    real_import = builtins.__import__

    def without_decoder(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "zstandard":
            raise ImportError("wheel unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_decoder)
    quota = claude_desktop.load_desktop_quota(NOW)
    assert quota is not None and quota.current_percent == 54
    assert quota.current_reset_at == (None if encoding == "zstd" else NOW + 100)


def test_invalid_zstd_frame_is_a_cache_miss(sources: Path) -> None:
    _cache(sources / "Cache/Cache_Data", Response())
    (sources / "Cache/Cache_Data/f_000001").write_bytes(b"\x28\xb5\x2f\xfdinvalid")
    assert (
        chromium_cache.load_cached_json(
            sources / "Cache/Cache_Data",
            b"https://claude.ai/api/organizations/org-a/usage",
            NOW - 1,
            NOW,
        )
        is None
    )


def test_fresh_import_and_code_quota_work_without_zstandard(sources: Path) -> None:
    # A fresh interpreter proves that import-time dependency loading cannot break
    # the normal Code path. All configuration and quota files belong to this test.
    script = """
import asyncio, importlib.abc, json, sys
from pathlib import Path
class BlockDecoder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "zstandard":
            raise ImportError("missing wheel")
sys.meta_path.insert(0, BlockDecoder())
from loaders import claude_usage as usage_client
from adapters import rate_limits
root = Path(sys.argv[1])
for module in (usage_client, rate_limits):
    for name in ("STATUS_FILE", "LEGACY_STATUS_FILE", "TT_STATUS_FILE"):
        setattr(module, name, str(root / name))
root.joinpath("STATUS_FILE").write_text(json.dumps({"rate_limits": {
    "five_hour": {"used_percentage": 22}, "seven_day": {"used_percentage": 33}
}}), encoding="utf-8")
assert asyncio.run(usage_client.ClaudeUsageClient().fetch_once()).snapshot.current_percent == 22
assert rate_limits.load_rate_limits().seven_day_pct == 33
assert "zstandard" not in sys.modules
print("ok")
"""
    env = dict(
        os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]), USERPROFILE=str(sources)
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(sources)],
        cwd=sources,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "ok"
