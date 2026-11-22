# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import urllib.parse
import webbrowser

import pytest

from usage_common import issue_report
from usage_common.issue_report import IssueEnvironment


def _env(**overrides: object) -> IssueEnvironment:
    values: dict[str, object] = {
        "usage_version": "1.2.3",
        "install_method": "source",
        "os_name": "Darwin",
        "os_version": "26.0",
        "cpu_arch": "arm64",
        "python_version": "3.13.0",
        "language": "zh-TW",
        "panel_theme": "classic",
        "visible_cards": {"Claude": True, "Codex": False},
    }
    values.update(overrides)
    return IssueEnvironment(**values)  # type: ignore[arg-type]


def _decoded_body(url: str) -> str:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return query["body"][0]


def test_body_has_sections_and_environment() -> None:
    body = issue_report.build_issue_body(_env())
    for section in (
        "**Describe the bug**",
        "**Steps to reproduce**",
        "**Expected behavior**",
        "**Environment**",
        "**Additional context**",
    ):
        assert section in body
    for field in ("1.2.3", "source", "Darwin 26.0", "arm64", "3.13.0", "zh-TW", "classic"):
        assert field in body
    assert "Claude=shown" in body
    assert "Codex=hidden" in body
    url = issue_report.build_issue_url(_env())
    assert url.startswith("https://github.com/aqua5230/usage/issues/new?")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert "template" not in query
    assert query["labels"] == ["bug"]


def test_url_never_contains_private_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = "/Users/fake-secret-user/secret-project"
    monkeypatch.setenv("HOME", fake_home)
    monkeypatch.setenv("USER", "fake-secret-user")
    monkeypatch.setenv("LOGNAME", "fake-secret-user")
    monkeypatch.setenv("HOSTNAME", "fake-secret-host")
    prefs = {
        "hide_claude_section": True,
        "hide_codex_section": False,
        "project_path": fake_home,
        "email": "fake@example.com",
    }
    url = issue_report.build_issue_url(issue_report.collect_environment("en", "classic", prefs))
    decoded = urllib.parse.unquote(url)
    for secret in (
        "fake-secret-user",
        "secret-project",
        fake_home,
        "fake-secret-host",
        "fake@example.com",
    ):
        assert secret not in decoded
    assert "/Users/" not in decoded
    assert "Claude=hidden" in _decoded_body(url)
    assert "Codex=shown" in _decoded_body(url)


def test_collect_environment_reads_hide_prefs() -> None:
    env = issue_report.collect_environment(
        "ko", "matrix", {"hide_agy_section": True, "hide_grok_section": True}
    )
    assert env.language == "ko"
    assert env.panel_theme == "matrix"
    assert env.visible_cards["Antigravity"] is False
    assert env.visible_cards["Grok"] is False
    assert env.visible_cards["Claude"] is True


def test_open_issue_report_uses_webbrowser(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    url = issue_report.open_issue_report("en", "classic", {})
    assert opened == [url]
    assert _decoded_body(url)
