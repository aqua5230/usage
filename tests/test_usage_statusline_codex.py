# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import re
import sys
import time
import tomllib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from installer import codex_statusline, setup_hook, statusline_settings
from usage_hooks import usage_statusline_codex as hook

# The provider is macOS-only, and the clock strings need tzset to pin TZ=UTC.
pytestmark = pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset unavailable")

NOW = datetime(2026, 11, 26, 10, 13, 20, tzinfo=UTC).timestamp()


@pytest.fixture(autouse=True)
def _utc_and_clean_memory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("TZ", "UTC")
    getattr(time, "tzset", lambda: None)()
    monkeypatch.setattr(hook, "QUOTA_SNAPSHOT", str(tmp_path / "quota_snapshot.json"))
    monkeypatch.setattr(hook, "PREFERENCES_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.setattr(hook, "SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr(hook, "_session_starts", {})
    monkeypatch.setattr(hook, "_context_samples", {})
    yield
    monkeypatch.undo()
    getattr(time, "tzset", lambda: None)()


def _state(**thread: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "thread-1",
        "model": {"display_name": "GPT-6.1 Terra", "reasoning_level": "high"},
        "usage": {
            "context": {"context_window_size": 475_000, "used_percentage": 12},
            "total": {"total_input_tokens": 1000, "cache_read_input_tokens": 900},
        },
    }
    base.update(thread)
    return {
        "account": {
            "rate_limits": [
                {
                    "limit_id": "codex",
                    "primary_limit": {"used_percent": 6, "resets_at": NOW + 3_900},
                    "secondary_limit": {"used_percent": 63, "resets_at": NOW + 4 * 86400},
                }
            ]
        },
        "thread": base,
    }


def _flat(node: Any) -> str:
    if isinstance(node, str):
        return node
    return "".join(_flat(child) for child in node.get("children", []) if child is not None)


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for child in node.get("children", []):
            yield from _walk(child)


def test_render_matches_claude_layout_on_one_line() -> None:
    tree = hook.render(_state(), now=NOW, lang="zh-TW")

    assert _flat(tree) == (
        "5小時:□□□□□□□□ 6% 11:18(剩1h5m) | 7天:■■■■■□□□ 63% 11/30 10:13(剩4d0h)"
        " | 會話時長: 0s | GPT-6.1 Terra/深思 | 快取:90% | 對話窗:■□□□□□□□ 12% / 475k"
    )


def test_tree_uses_only_what_codex_0172_accepts() -> None:
    # 0.172 has no col/box/spacer/badge and no preserveWhitespace/maxLines.
    tree = hook.render(_state(workspace={"cwd": "/tmp/project"}), now=NOW, lang="en")
    nodes = list(_walk(tree))

    assert {node["type"] for node in nodes} == {"text"}
    assert {key for node in nodes for key in node.get("props", {})} <= {"color"}
    assert all(
        re.fullmatch(r"#[0-9a-f]{6}", node["props"]["color"]) for node in nodes if "props" in node
    )
    assert len(nodes) + sum(isinstance(c, str) for n in nodes for c in n["children"]) <= 256


def test_project_and_branch_come_first(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/feat/x\n", encoding="utf-8")

    text = _flat(hook.render(_state(workspace={"cwd": str(tmp_path)}), now=NOW, lang="en"))

    assert text.startswith(f"{tmp_path.name}(feat/x) | 5h:")


def test_falls_back_to_usage_snapshot_before_first_response(tmp_path: Path) -> None:
    snapshot = {
        "agents": {
            "codex": {
                "available": True,
                "five_hour": {"used_percent": 40.0, "resets_at": NOW + 600},
                "seven_day": {"used_percent": 70.0, "resets_at": NOW + 7200},
            }
        }
    }
    Path(hook.QUOTA_SNAPSHOT).write_text(json.dumps(snapshot), encoding="utf-8")
    state = _state()
    state["account"]["rate_limits"] = []

    text = _flat(hook.render(state, now=NOW, lang="en"))

    assert "5h:■■■□□□□□ 40% 10:23(10min left)" in text
    assert "7d:■■■■■■□□ 70% 12:13(2h0m left)" in text


def test_expired_window_reads_zero_and_full_window_shows_reset_only() -> None:
    state = _state()
    limits = state["account"]["rate_limits"][0]
    limits["primary_limit"] = {"used_percent": 80, "resets_at": NOW - 1}
    limits["secondary_limit"] = {"used_percent": 100, "resets_at": NOW + 60}

    text = _flat(hook.render(state, now=NOW, lang="en"))

    assert "5h:□□□□□□□□ 0% |" in text
    assert "7d:10:14(1min left) |" in text


def test_heavy_context_warning_leads_the_line() -> None:
    state = _state()
    state["thread"]["usage"]["context"]["used_percentage"] = 72

    text = _flat(hook.render(state, now=NOW, lang="en"))

    assert text.startswith("⚠ Context 72% · longer chats lose the middle")


def test_fast_context_growth_lowers_the_warning_threshold() -> None:
    assert hook.heavy_threshold("t", 40.0, NOW) == 70.0
    assert hook.heavy_threshold("t", 40.0, NOW + 30) == 70.0
    # 40% -> 58% over three minutes is 6% a minute: very fast.
    assert hook.heavy_threshold("t", 58.0, NOW + 180) == 55.0
    assert hook.heavy_threshold("t", 58.0, NOW + 400) == 55.0
    # A drop of more than 5 points (a /compact) resets it.
    assert hook.heavy_threshold("t", 20.0, NOW + 500) == 70.0


def test_session_start_reads_rollout_name_then_first_sight(tmp_path: Path) -> None:
    assert hook.session_start("abc", NOW) == NOW
    assert hook.session_start("abc", NOW + 50) == NOW

    folder = Path(hook.SESSIONS_DIR) / "2026" / "11" / "26"
    folder.mkdir(parents=True)
    (folder / "rollout-2026-11-26T09-13-20-abc.jsonl").write_text("", encoding="utf-8")

    assert hook.session_start("abc", NOW + 60) == NOW - 3600


def test_update_hint_is_appended(tmp_path: Path) -> None:
    prefs = {
        "last_update_check": {
            "latest_version": "1.9.0",
            "current_version": "1.8.0",
            "checked_at": NOW - 60,
        }
    }
    Path(hook.PREFERENCES_FILE).write_text(json.dumps(prefs), encoding="utf-8")

    assert _flat(hook.render(_state(), now=NOW, lang="en")).endswith(" | 🆕 v1.9.0 available")


def test_effort_and_language_follow_the_claude_labels() -> None:
    state = _state()
    state["thread"]["model"]["reasoning_level"] = "medium"

    assert "GPT-6.1 Terra/標準" in _flat(hook.render(state, now=NOW, lang="ja"))
    assert hook.detect_lang({"USAGE_LANG": "ko_KR.UTF-8", "LANG": "zh_TW.UTF-8"}) == "ko"


def test_render_error_still_returns_drawable_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(state: dict[str, Any]) -> Any:
        raise RuntimeError

    monkeypatch.setattr(hook, "render", boom)

    assert hook.safe_render({}) == "usage"


def test_protocol_round_trip() -> None:
    tools = hook.handle_line(b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
    assert tools is not None
    meta = tools["result"]["tools"][0]["_meta"]
    assert meta["ui"] == {"visibility": ["app"]}
    entry = meta["openai/ui"]["entrypoints"][0]
    assert entry == {"type": "statusline", "resourceUri": hook.URI}

    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "resources/read",
        "params": {"uri": hook.URI, "_meta": {hook.STATE_KEY: _state()}},
    }
    read = hook.handle_line(json.dumps(request).encode())
    assert read is not None
    content = read["result"]["contents"][0]
    assert content["mimeType"] == "application/json"
    assert "GPT-6.1 Terra" in _flat(json.loads(content["text"]))

    assert hook.handle_line(b'{"jsonrpc":"2.0","method":"notifications/initialized"}') is None
    unknown = hook.handle_line(b'{"jsonrpc":"2.0","id":3,"method":"nope"}')
    assert unknown is not None and unknown["error"]["code"] == -32601
    garbage = hook.handle_line(b"{not json")
    assert garbage is not None and garbage["error"]["code"] == -32700


# --- installer -------------------------------------------------------------------

BASE_CONFIG = """model = "gpt-6.1-terra"

[features]
hooks = true

[tui]
status_line = ["project", "five-hour-limit"]

[mcp_servers.other]
command = "other"
"""


@pytest.fixture
def codex_config(monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(codex_statusline, "codex_version", lambda: (0, 172, 0))
    path = setup_hook.CODEX_CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BASE_CONFIG, encoding="utf-8")
    return path


def _parsed(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_setup_adds_server_flag_and_selection_only(codex_config: Path) -> None:
    assert codex_statusline.setup() is True

    parsed = _parsed(codex_config)
    assert parsed["mcp_servers"]["usage-statusline"] == {
        "command": "/usr/bin/python3",
        "args": ["-u", str(codex_statusline.PROVIDER_TARGET)],
        "env_vars": ["USAGE_LANG", "TT_LANG", "CODEX_HOME"],
    }
    assert parsed["features"] == {"hooks": True, "tui_extensions_statusline": True}
    assert parsed["tui"]["status_line_provider"] == {
        "server": "usage-statusline",
        "tool": "statusline",
    }
    assert parsed["tui"]["status_line"] == ["project", "five-hour-limit"]
    assert parsed["mcp_servers"]["other"] == {"command": "other"}
    assert codex_statusline.PROVIDER_TARGET.read_bytes() == Path(hook.__file__).read_bytes()
    assert codex_statusline.is_setup() and not codex_statusline.script_is_stale()

    before = codex_config.read_text(encoding="utf-8")
    assert codex_statusline.setup() is True
    assert codex_config.read_text(encoding="utf-8") == before


def test_unsetup_restores_the_original_config(codex_config: Path) -> None:
    codex_statusline.setup()

    assert codex_statusline.unsetup() is True

    assert _parsed(codex_config) == tomllib.loads(BASE_CONFIG)
    assert not codex_statusline.PROVIDER_STATE.exists()


def test_unsetup_keeps_a_flag_the_user_set(codex_config: Path) -> None:
    codex_config.write_text(
        BASE_CONFIG.replace("hooks = true", "hooks = true\ntui_extensions_statusline = true"),
        encoding="utf-8",
    )
    codex_statusline.setup()
    codex_statusline.unsetup()

    assert _parsed(codex_config)["features"]["tui_extensions_statusline"] is True


@pytest.mark.parametrize(
    "config",
    [
        BASE_CONFIG.replace(
            'five-hour-limit"]', 'five-hour-limit"]\nstatus_line_provider = "default"'
        ),
        BASE_CONFIG.replace("hooks = true", "hooks = true\ntui_extensions_statusline = false"),
    ],
)
def test_setup_respects_the_users_choice(codex_config: Path, config: str) -> None:
    codex_config.write_text(config, encoding="utf-8")

    assert codex_statusline.setup() is False
    assert codex_config.read_text(encoding="utf-8") == config


def test_setup_needs_codex_0172(codex_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codex_statusline, "codex_version", lambda: (0, 171, 0))

    assert codex_statusline.setup() is False
    assert codex_config.read_text(encoding="utf-8") == BASE_CONFIG


def test_setup_is_macos_only(codex_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    assert codex_statusline.setup() is False
    assert codex_config.read_text(encoding="utf-8") == BASE_CONFIG


def test_setup_then_unsetup_restores_the_exact_bytes(codex_config: Path) -> None:
    codex_statusline.setup()
    codex_statusline.unsetup()

    assert codex_config.read_text(encoding="utf-8") == BASE_CONFIG


def test_a_same_named_server_of_the_users_is_never_touched(codex_config: Path) -> None:
    config = BASE_CONFIG + '\n[mcp_servers.usage-statusline]\ncommand = "/custom/provider"\n'
    codex_config.write_text(config, encoding="utf-8")

    assert codex_statusline.setup() is False
    assert codex_statusline.unsetup() is False
    assert codex_config.read_text(encoding="utf-8") == config


def test_an_older_install_of_ours_is_upgraded(codex_config: Path) -> None:
    old = (
        BASE_CONFIG
        + '\n[mcp_servers.usage-statusline]\ncommand = "/usr/bin/python3"\n'
        + f'args = ["-u", "{codex_statusline.PROVIDER_TARGET}"]\n'
    )
    codex_config.write_text(old, encoding="utf-8")

    assert codex_statusline.setup() is True
    assert _parsed(codex_config)["mcp_servers"]["usage-statusline"]["env_vars"] == [
        "USAGE_LANG",
        "TT_LANG",
        "CODEX_HOME",
    ]


@pytest.mark.parametrize(
    "config",
    [
        'tui.status_line = [\n  "project",\n]\n\n[features]\nhooks = true\n',
        'tui = { status_line = ["project"] }\n\n[features]\nhooks = true\n',
        '["features"]\nhooks = true\n\n[tui]\nstatus_line = ["project"]\n',
    ],
)
def test_shapes_usage_cannot_edit_are_left_whole(codex_config: Path, config: str) -> None:
    codex_config.write_text(config, encoding="utf-8")

    assert codex_statusline.setup() is False
    assert codex_config.read_text(encoding="utf-8") == config
    assert not codex_statusline.PROVIDER_TARGET.exists()


def test_unsetup_removes_a_selection_written_as_a_subtable(codex_config: Path) -> None:
    codex_statusline.setup()
    text = codex_config.read_text(encoding="utf-8").replace(
        'status_line_provider = { server = "usage-statusline", tool = "statusline" }\n', ""
    )
    text += (
        '\n[tui.status_line_provider]\nserver = "usage-statusline"\ntool = "statusline"\n'
        '\n# notes for the next table\n[mcp_servers.after]\ncommand = "after"\n'
    )
    codex_config.write_text(text, encoding="utf-8")

    assert codex_statusline.unsetup() is True

    after = codex_config.read_text(encoding="utf-8")
    assert "status_line_provider" not in _parsed(codex_config)["tui"]
    assert "usage-statusline" not in _parsed(codex_config)["mcp_servers"]
    assert "# notes for the next table\n[mcp_servers.after]" in after


def test_unsetup_keeps_the_flag_another_provider_now_needs(codex_config: Path) -> None:
    codex_statusline.setup()
    text = codex_config.read_text(encoding="utf-8").replace(
        'server = "usage-statusline", tool = "statusline"', 'server = "other", tool = "x"'
    )
    codex_config.write_text(text, encoding="utf-8")

    assert codex_statusline.unsetup() is True
    parsed = _parsed(codex_config)
    assert parsed["features"]["tui_extensions_statusline"] is True
    assert parsed["tui"]["status_line_provider"] == {"server": "other", "tool": "x"}


def test_a_failed_config_write_records_nothing(
    codex_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = setup_hook._atomic_write_text

    def failing_write(path: Path, content: str, encoding: str = "utf-8") -> None:
        if path == setup_hook.CODEX_CONFIG:
            raise OSError("disk full")
        real_write(path, content, encoding)

    monkeypatch.setattr(setup_hook, "_atomic_write_text", failing_write)

    assert codex_statusline.setup() is False
    assert not codex_statusline.PROVIDER_STATE.exists()


def test_a_stale_record_never_claims_the_users_own_flag(codex_config: Path) -> None:
    codex_config.write_text(
        BASE_CONFIG.replace("hooks = true", "hooks = true\ntui_extensions_statusline = true"),
        encoding="utf-8",
    )
    codex_statusline.PROVIDER_STATE.write_text('{"added_feature": true}\n', encoding="utf-8")

    codex_statusline.setup()
    codex_statusline.unsetup()

    assert _parsed(codex_config)["features"]["tui_extensions_statusline"] is True


def test_the_switch_turns_off_a_codex_only_install(codex_config: Path) -> None:
    assert codex_statusline.setup() is True
    assert statusline_settings._statusline_enabled() is True

    assert statusline_settings._toggle_statusline_settings() == ("uninstall", 0)
    assert not codex_statusline.is_setup()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rate_limits", 7),
        ("primary_limit", "bad"),
        ("resets_at", "inf"),
        ("used_percent", "NaN"),
        ("context_window_size", -475_000),
    ],
)
def test_one_bad_field_never_blanks_the_line(field: str, value: Any) -> None:
    state = _state()
    limits = state["account"]["rate_limits"][0]
    if field == "rate_limits":
        state["account"]["rate_limits"] = value
    elif field == "primary_limit":
        limits["primary_limit"] = value
    elif field == "context_window_size":
        state["thread"]["usage"]["context"]["context_window_size"] = value
    else:
        limits["primary_limit"][field] = value

    text = _flat(hook.render(state, now=NOW, lang="en"))

    assert "GPT-6.1 Terra/Deep" in text
    assert "100%" not in text and "-475000" not in text


def test_an_unknown_resource_gets_the_mcp_not_found_code() -> None:
    reply = hook.handle_line(
        b'{"jsonrpc":"2.0","id":4,"method":"resources/read","params":{"uri":"ui://x"}}'
    )
    assert reply is not None and reply["error"]["code"] == -32002
