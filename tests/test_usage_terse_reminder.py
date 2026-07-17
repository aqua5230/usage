# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import usage_terse_reminder as mod


def test_detect_lang_uses_windows_system_lang_when_env_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("USAGE_LANG", "TT_LANG", "LANG"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(mod, "_windows_system_lang", lambda: "zh_TW")

    assert mod._detect_lang() == "zh-TW"


def test_detect_lang_prefers_usage_lang_over_windows_system_lang(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USAGE_LANG", "ja")
    monkeypatch.setattr(mod, "_windows_system_lang", lambda: "zh_TW")

    assert mod._detect_lang() == "ja"


def test_windows_system_lang_is_empty_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "os", SimpleNamespace(name="posix"))

    assert mod._windows_system_lang() == ""


def _sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sidecar = tmp_path / "usage-terse-prompt.json"
    sidecar.write_text(
        json.dumps(
            {
                "en": {"reminder": "REMINDER::EN"},
                "zh-TW": {"reminder": "提醒::繁中"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "PROMPT_SIDECAR", sidecar)


class _FakeStdin:
    def __init__(self, data: str) -> None:
        self._data = data

    def read(self) -> str:
        return self._data


def test_main_reads_sidecar_reminder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.stdin", _FakeStdin(json.dumps({"prompt": "hi"})))

    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert out["hookSpecificOutput"]["additionalContext"] == "REMINDER::EN"


def test_main_falls_back_to_default_when_sidecar_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setattr(mod, "PROMPT_SIDECAR", tmp_path / "missing.json")
    monkeypatch.setattr("sys.stdin", _FakeStdin(json.dumps({"prompt": "hi"})))

    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out)
    context = out["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("[")
    assert context.endswith("]")
    assert "Terse mode is still on" in context


def test_main_uses_detected_language(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("USAGE_LANG", "zh-TW")
    _sidecar(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.stdin", _FakeStdin(json.dumps({"prompt": "hi"})))

    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["additionalContext"] == "提醒::繁中"


def test_main_reads_utf8_bytes_when_stdin_uses_cp950(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    payload = json.dumps(
        {"cwd": r"C:\\Users\\USER\\Desktop\\GitHub專案\\usage"}, ensure_ascii=False
    )
    monkeypatch.setattr(
        "sys.stdin", io.TextIOWrapper(io.BytesIO(payload.encode("utf-8")), encoding="cp950")
    )

    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["additionalContext"] == "REMINDER::EN"


def test_main_is_silent_on_invalid_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", _FakeStdin("{"))
    assert mod.main() == 0
    assert capsys.readouterr().out == ""


def test_main_emits_reminder_for_empty_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _sidecar(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.stdin", _FakeStdin("{}"))

    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["additionalContext"] == "REMINDER::EN"


def test_main_falls_back_to_en_when_sidecar_lacks_lang(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("USAGE_LANG", "ja")
    _sidecar(tmp_path, monkeypatch)  # only en + zh-TW in sidecar
    monkeypatch.setattr("sys.stdin", _FakeStdin(json.dumps({"prompt": "hi"})))

    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["additionalContext"] == "REMINDER::EN"
