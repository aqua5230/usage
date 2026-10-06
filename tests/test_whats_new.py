from __future__ import annotations

import io
import json
import subprocess
import sys
import urllib.error
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from updates import whats_new
from updates.checker import ReleaseCheckResult, ReleaseInfo
from updates.release_notes import format_release_notes, select_release_notes

RELEASE = ReleaseInfo("0.32.5", "https://github.com/aqua5230/usage/releases/tag/v0.32.5", "Notes")


@pytest.mark.parametrize("language", ["zh-TW", "zh-CN", "en", "ja", "ko", "unknown"])
def test_language_sections(language: str) -> None:
    expected = "中文" if language in ("zh-TW", "zh-CN") else "English"
    assert select_release_notes("English\n\n## 繁體中文\n\n中文", language) == expected
    assert select_release_notes("Old notes", language) == "Old notes"
    assert select_release_notes("English\n## 繁體中文\n  ", language) == "English"


@pytest.mark.parametrize("body", ["", "## 繁體中文", "\n## 繁體中文\n"])
def test_empty_sections(body: str) -> None:
    assert select_release_notes(body, "zh-TW") == ""
    assert format_release_notes(select_release_notes(body, "zh-TW"), 2000) == ""


def test_exact_marker_and_line_endings() -> None:
    assert select_release_notes("EN\r\n## 繁體中文\r\n中文", "zh-TW") == "中文"
    assert select_release_notes("EN\n## 繁體中文 extra\n中文", "zh-TW").startswith("EN")
    assert select_release_notes("EN\ntext ## 繁體中文\n中文", "zh-TW").startswith("EN")
    assert format_release_notes(select_release_notes("EN\n## 繁體中文\n中文", "zh-TW"), 0) == ""


@pytest.mark.parametrize(
    ("snapshot", "action"),
    [
        ({}, "record"),
        ({"language": "en"}, "fetch"),
        ({"last_launched_version": "0.32.5"}, "none"),
        ({"last_launched_version": "0.32.4"}, "fetch"),
        ({"last_launched_version": "0.33.0"}, "record"),
        ({"last_launched_version": "invalid"}, "record"),
        ({"last_launched_version": None}, "record"),
    ],
)
def test_launch_decisions(snapshot: dict[str, Any], action: str) -> None:
    assert whats_new.launch_action("0.32.5", snapshot) == action


@pytest.mark.parametrize(
    ("result", "action"),
    [
        (ReleaseCheckResult(None, failed=True), "retry"),
        (ReleaseCheckResult(None), "record"),
        (ReleaseCheckResult(ReleaseInfo("0.32.5", RELEASE.html_url, "")), "record"),
        (ReleaseCheckResult(ReleaseInfo("0.32.5", RELEASE.html_url, " \n")), "record"),
        (ReleaseCheckResult(RELEASE), "show"),
    ],
)
def test_release_decisions(result: ReleaseCheckResult, action: str) -> None:
    assert whats_new.release_action(result) == action


@pytest.mark.parametrize("status", [404, 403, 429, 500])
def test_http_outcomes(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise urllib.error.HTTPError("https://example.test", status, "error", Message(), None)

    monkeypatch.setattr("updates.whats_new.urllib.request.urlopen", fail)
    result = whats_new.fetch_release("0.32.5")
    assert result.failed == (status != 404)
    assert whats_new.release_action(result) == ("record" if status == 404 else "retry")


@pytest.mark.parametrize("error", [TimeoutError("timeout"), urllib.error.URLError("offline")])
def test_network_failure(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise error

    monkeypatch.setattr("updates.whats_new.urllib.request.urlopen", fail)
    assert whats_new.release_action(whats_new.fetch_release("0.32.5")) == "retry"


@pytest.mark.parametrize("body", ["", "Notes"])
def test_tag_request(monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    def response(request: Any, *, timeout: float) -> io.BytesIO:
        assert request.full_url.endswith("/releases/tags/v0.32.5")
        assert timeout == 5.0
        assert request.get_header("User-agent") == "usage/0.32.5"
        assert request.get_header("Accept") == "application/vnd.github+json"
        return io.BytesIO(
            json.dumps(
                {
                    "tag_name": "v0.32.5",
                    "html_url": RELEASE.html_url,
                    "body": body,
                }
            ).encode()
        )

    monkeypatch.setattr("updates.whats_new.urllib.request.urlopen", response)
    result = whats_new.fetch_release("0.32.5")
    assert result.release is not None
    assert result.release.body == body
    assert whats_new.release_action(result) == ("show" if body else "record")


@pytest.mark.parametrize("payload", [b"not JSON", b"{}", b"[]", b"\xff"])
def test_bad_response_retries(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
    monkeypatch.setattr(
        "updates.whats_new.urllib.request.urlopen", lambda *a, **k: io.BytesIO(payload)
    )
    assert whats_new.fetch_release("0.32.5").failed


def test_background_dispatch_and_record_after_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    workers: list[Callable[[], None]] = []
    callbacks: list[Callable[[], None]] = []
    events: list[str] = []
    preferences = {"changed_during_request": True}
    monkeypatch.setattr(whats_new, "_load_preferences", lambda: dict(preferences))
    monkeypatch.setattr(whats_new, "_save_preferences", lambda value: preferences.update(value))
    monkeypatch.setattr(whats_new, "fetch_release", lambda version: ReleaseCheckResult(RELEASE))

    class Thread:
        def __init__(
            self, *, target: Callable[..., None], args: tuple[Any, ...], daemon: bool
        ) -> None:
            assert daemon
            workers.append(lambda: target(*args))

        def start(self) -> None:
            pass

    monkeypatch.setattr("updates.whats_new.threading.Thread", Thread)

    def show(release: ReleaseInfo) -> bool:
        assert "last_launched_version" not in preferences
        events.append("show")
        return False

    whats_new.start_notice("0.32.5", {"language": "en"}, show, callbacks.append)
    assert not callbacks and not events
    workers[0]()
    assert not events and "last_launched_version" not in preferences
    callbacks[0]()
    assert events == ["show"]
    assert preferences == {"changed_during_request": True, "last_launched_version": "0.32.5"}
    whats_new.start_notice("0.32.5", preferences, show, callbacks.append)
    assert len(workers) == 1  # Same version does not fetch or show again.


@pytest.mark.parametrize(
    "result",
    [
        ReleaseCheckResult(None),
        ReleaseCheckResult(None, failed=True),
        ReleaseCheckResult(ReleaseInfo("0.32.5", RELEASE.html_url, "")),
    ],
)
def test_worker_silent_outcomes(
    monkeypatch: pytest.MonkeyPatch, result: ReleaseCheckResult
) -> None:
    recorded: list[str] = []
    monkeypatch.setattr(whats_new, "fetch_release", lambda version: result)
    monkeypatch.setattr(whats_new, "record_version", recorded.append)

    def unexpected(*args: Any) -> Any:
        pytest.fail("silent outcome must not show or dispatch an alert")

    whats_new._fetch_and_dispatch("0.32.5", unexpected, unexpected)
    assert recorded == ([] if result.failed else ["0.32.5"])


def test_fresh_launch_records_without_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[str] = []
    monkeypatch.setattr(whats_new, "record_version", recorded.append)
    monkeypatch.setattr(
        whats_new, "fetch_release", lambda version: pytest.fail("unexpected network")
    )
    whats_new.start_notice("0.32.5", {}, lambda release: False, lambda callback: None)
    assert recorded == ["0.32.5"]


def _release_script() -> str:
    workflow = (Path(__file__).parents[1] / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )
    section = workflow.split("      - name: Extract release notes from CHANGELOG.md", 1)[1]
    script = section.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0]
    return "\n".join(line.removeprefix("          ") for line in script.splitlines())


@pytest.mark.skipif(sys.platform == "win32", reason="release.yml runs this step on macOS")
@pytest.mark.parametrize("chinese", [None, "## [9.9.9]\nOther\n", "## [1.2.3]\n中文\n"])
def test_release_workflow_sections(tmp_path: Path, chinese: str | None) -> None:
    (tmp_path / "CHANGELOG.md").write_text(
        "## [1.2.3]\nEnglish\n## [1.2.2]\nOld\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    if chinese is not None:
        (tmp_path / "docs/CHANGELOG.zh-TW.md").write_text(chinese, encoding="utf-8")
    output = tmp_path / "output"
    script = 'export TAG=v1.2.3\nexport GITHUB_OUTPUT="$PWD/output"\n' + _release_script()
    subprocess.run(["bash", "-c", script], cwd=tmp_path, check=True)
    notes = Path(output.read_text(encoding="utf-8").strip().removeprefix("path="))
    body = notes.read_text(encoding="utf-8")
    assert body.startswith("English\n")
    assert ("## 繁體中文" in body) == (chinese is not None and "1.2.3" in chinese)


@pytest.mark.parametrize("answer", [6, 7])
def test_windows_localized_notice(monkeypatch: pytest.MonkeyPatch, answer: int) -> None:
    from wintray import whats_new as windows_notice

    boxes: list[tuple[str, int]] = []

    def message_box(text: str, style: int) -> int:
        boxes.append((text, style))
        return answer

    monkeypatch.setattr(windows_notice, "_message_box", message_box)
    selected = windows_notice.show_notice(
        ReleaseInfo("0.32.5", RELEASE.html_url, "English\n## 繁體中文\n- **中文**"), "zh-TW"
    )
    assert boxes == [("usage 0.32.5 更新內容\n\n• 中文\n\n要在瀏覽器開啟完整說明嗎？", 0x44)]
    assert selected == (answer == 6)


def test_startup_snapshot_precedes_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from types import SimpleNamespace

    import main

    preferences: dict[str, Any] = {}
    snapshots: list[dict[str, Any]] = []
    monkeypatch.setattr(main, "_setup_logging", lambda: None)
    monkeypatch.setattr(main, "_load_preferences", lambda: dict(preferences))
    monkeypatch.setattr(main, "_self_heal", lambda: preferences.update({"repair": True}))
    monkeypatch.setattr(sys, "argv", ["usage"])
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        main,
        "parse_args",
        lambda: SimpleNamespace(
            doctor=False,
            setup=False,
            unsetup=False,
            tui=False,
            mock=False,
            interval=60,
        ),
    )
    monkeypatch.setattr(
        "main.importlib.import_module",
        lambda name: SimpleNamespace(
            run_app=lambda **kwargs: snapshots.append(kwargs["preferences_snapshot"])
        ),
    )
    main.main()
    assert preferences == {"repair": True}
    assert snapshots == [{}]


@pytest.mark.parametrize("open_notes", [False, True])
def test_record_before_browser(monkeypatch: pytest.MonkeyPatch, open_notes: bool) -> None:
    events: list[str] = []
    monkeypatch.setattr(whats_new, "fetch_release", lambda version: ReleaseCheckResult(RELEASE))
    monkeypatch.setattr(whats_new, "record_version", lambda version: events.append("record"))
    monkeypatch.setattr("updates.whats_new.webbrowser.open", lambda url: events.append(url))

    def show(release: ReleaseInfo) -> bool:
        events.append("show")
        return open_notes

    whats_new._fetch_and_dispatch("0.32.5", show, lambda callback: callback())
    assert events == ["show", "record"] + ([RELEASE.html_url] if open_notes else [])


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS app imports")
@pytest.mark.parametrize("button", [1000, 1001])
def test_macos_notice_and_dispatch(monkeypatch: pytest.MonkeyPatch, button: int) -> None:
    from menubar import whats_new as mac_notice

    texts: list[str] = []
    buttons: list[str] = []

    class Alert:
        def setMessageText_(self, text: str) -> None:
            texts.append(text)

        def setInformativeText_(self, text: str) -> None:
            texts.append(text)

        def addButtonWithTitle_(self, text: str) -> None:
            buttons.append(text)

        def runModal(self) -> int:
            return button

    monkeypatch.setattr("menubar.chrome._make_alert", Alert)
    selected = mac_notice.show_notice(
        ReleaseInfo("0.32.5", RELEASE.html_url, "EN\n## 繁體中文\n- **中文**"), "zh-CN"
    )
    assert texts == ["usage 0.32.5 更新内容", "• 中文"]
    assert buttons == ["好", "完整说明"]
    assert selected == (button == 1001)
    callbacks: list[Callable[[], None]] = []
    monkeypatch.setattr("PyObjCTools.AppHelper.callAfter", callbacks.append)

    def callback() -> None:
        pass

    mac_notice._dispatch(callback)
    assert callbacks == [callback]


def test_windows_message_box_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from wintray import whats_new as windows_notice

    calls: list[tuple[Any, ...]] = []

    def message_box(*args: Any) -> int:
        calls.append(args)
        return 6

    monkeypatch.setattr(
        "wintray.whats_new.ctypes.windll",
        SimpleNamespace(user32=SimpleNamespace(MessageBoxW=message_box)),
        raising=False,
    )
    assert windows_notice._message_box("Notes", 0x44) == 6
    assert calls == [(0, "Notes", "usage", 0x44)]
