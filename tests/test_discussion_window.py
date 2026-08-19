# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast

import pytest

import discussion_window
from discussion_session import DebateStyle

HTML_PATH = Path(__file__).resolve().parents[1] / "assets" / "windows" / "discussion.html"
I18N_PATH = Path(__file__).resolve().parents[1] / "i18n.json"


class FakeWebView:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def evaluateJavaScript_completionHandler_(
        self,
        script: str,
        completion: object,
    ) -> None:
        self.scripts.append(script)


class FakeBridge:
    def __init__(self, working_directory: str | None = None) -> None:
        self.started: tuple[str, list[object], str | None, str | None] | None = None
        self.stop_count = 0
        self.clear_count = 0
        self.clear_status: dict[str, str] = {"status": "ok"}
        self.working_directory = working_directory
        self.attachments: object = None
        self.end_on_consensus = False
        self.guidance_between_rounds = False
        self.submitted_guidance: list[str] = []

    def start(
        self,
        topic: str,
        participants: list[object],
        moderator_id: str | None,
        working_directory: str | None = None,
        attachments: object = None,
        total_rounds: int = 2,
        include_summary: bool = True,
        end_on_consensus: bool = False,
        guidance_between_rounds: bool = False,
        debate_style: DebateStyle = DebateStyle.CONSTRUCTIVE,
    ) -> str:
        self.started = (topic, participants, moderator_id, working_directory)
        self.working_directory = working_directory
        self.attachments = attachments
        self.end_on_consensus = end_on_consensus
        self.guidance_between_rounds = guidance_between_rounds
        return "session"

    def submit_guidance(self, text: str) -> None:
        self.submitted_guidance.append(text)

    def stop(self) -> None:
        self.stop_count += 1

    def clear(self) -> dict[str, str]:
        self.clear_count += 1
        return self.clear_status

    def snapshot(self) -> dict[str, object]:
        return {
            "session_id": "session",
            "status": "PREPARING",
            "working_directory": self.working_directory,
        }

    def detect_participants(self) -> list[object]:
        return []

    def set_event_listener(self, callback: object) -> None:
        return None


class VisibleMarkupTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden_depth = 0
        self.text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.hidden_depth == 0 and data.strip():
            self.text.append(data.strip())


@pytest.mark.parametrize(
    ("raw", "action"),
    [
        ('{"action":"discussion_attach"}', "discussion_attach"),
        ('{"action":"discussion_detect"}', "discussion_detect"),
        ('{"action":"discussion_pick_folder"}', "discussion_pick_folder"),
        ('{"action":"discussion_clear_folder"}', "discussion_clear_folder"),
        ('{"action":"discussion_clear"}', "discussion_clear"),
        ('{"action":"discussion_stop"}', "discussion_stop"),
    ],
)
def test_parse_simple_actions(raw: str, action: str) -> None:
    assert discussion_window.parse_discussion_action(raw).action == action


def test_parse_start_action_validates_and_normalizes_fields() -> None:
    action = discussion_window.parse_discussion_action(
        json.dumps(
            {
                "action": "discussion_start",
                "topic": "問題",
                "participants": ["claude", "codex"],
                "moderatorId": "codex",
                "workingDir": "/tmp/project",
            }
        )
    )

    assert action.topic == "問題"
    assert action.participants == ("claude", "codex")
    assert action.moderator_id == "codex"
    assert action.working_directory == "/tmp/project"


def test_parse_start_action_clamps_total_rounds() -> None:
    action = discussion_window.parse_discussion_action(
        json.dumps(
            {
                "action": "discussion_start",
                "topic": "問題",
                "participants": ["claude"],
                "totalRounds": 99,
                "includeSummary": False,
            }
        )
    )

    assert action.total_rounds == 5
    assert action.include_summary is False
    assert action.end_on_consensus is False
    assert action.debate_style is DebateStyle.CONSTRUCTIVE


def test_parse_start_action_accepts_end_on_consensus() -> None:
    action = discussion_window.parse_discussion_action(
        json.dumps(
            {
                "action": "discussion_start",
                "topic": "問題",
                "participants": ["claude", "codex"],
                "endOnConsensus": True,
            }
        )
    )

    assert action.end_on_consensus is True


def test_parse_start_action_rejects_non_boolean_end_on_consensus() -> None:
    with pytest.raises(ValueError, match="endOnConsensus"):
        discussion_window.parse_discussion_action(
            json.dumps(
                {
                    "action": "discussion_start",
                    "topic": "問題",
                    "participants": ["claude", "codex"],
                    "endOnConsensus": 1,
                }
            )
        )


@pytest.mark.parametrize("style", list(DebateStyle))
def test_parse_start_action_accepts_debate_styles(style: DebateStyle) -> None:
    action = discussion_window.parse_discussion_action(
        json.dumps(
            {
                "action": "discussion_start",
                "topic": "問題",
                "participants": ["claude"],
                "debateStyle": style.value,
            }
        )
    )

    assert action.debate_style is style


def test_parse_start_action_rejects_unknown_debate_style() -> None:
    with pytest.raises(ValueError):
        discussion_window.parse_discussion_action(
            json.dumps(
                {
                    "action": "discussion_start",
                    "topic": "問題",
                    "participants": ["claude"],
                    "debateStyle": "unknown",
                }
            )
        )


def test_parse_start_action_models_optional_defaults_empty() -> None:
    action = discussion_window.parse_discussion_action(
        json.dumps(
            {
                "action": "discussion_start",
                "topic": "x",
                "participants": ["claude"],
            }
        )
    )
    assert action.models == {}
    assert action.personas == {}


def test_parse_start_action_personas_accept_strings_and_null() -> None:
    action = discussion_window.parse_discussion_action(
        json.dumps(
            {
                "action": "discussion_start",
                "topic": "x",
                "participants": ["claude", "codex"],
                "personas": {"claude": "contract-review", "codex": None},
            }
        )
    )

    assert action.personas == {"claude": "contract-review", "codex": None}


@pytest.mark.parametrize(
    "personas",
    [
        [],
        {"other": "contract-review"},
        {"claude": 1},
    ],
)
def test_parse_start_action_rejects_invalid_personas(personas: object) -> None:
    with pytest.raises(ValueError):
        discussion_window.parse_discussion_action(
            json.dumps(
                {
                    "action": "discussion_start",
                    "topic": "x",
                    "participants": ["claude"],
                    "personas": personas,
                }
            )
        )


def test_parse_start_action_rejects_unknown_model_value() -> None:
    with pytest.raises(ValueError):
        discussion_window.parse_discussion_action(
            json.dumps(
                {
                    "action": "discussion_start",
                    "topic": "x",
                    "participants": ["claude"],
                    "models": {"claude": "gpt-5.6-sol"},
                }
            )
        )


def test_parse_start_action_rejects_unknown_model_participant() -> None:
    with pytest.raises(ValueError):
        discussion_window.parse_discussion_action(
            json.dumps(
                {
                    "action": "discussion_start",
                    "topic": "x",
                    "participants": ["claude"],
                    "models": {"other": "opus"},
                }
            )
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"action": "unknown"},
        {"action": "discussion_start", "topic": 1, "participants": ["claude"]},
        {"action": "discussion_start", "topic": "x", "participants": []},
        {"action": "discussion_start", "topic": "x", "participants": ["other"]},
        {
            "action": "discussion_start",
            "topic": "x",
            "participants": ["claude", "claude"],
        },
        {
            "action": "discussion_start",
            "topic": "x",
            "participants": ["claude"],
            "moderatorId": "codex",
        },
        {
            "action": "discussion_start",
            "topic": "x",
            "participants": ["claude"],
            "workingDir": 1,
        },
    ],
)
def test_parse_action_rejects_bad_parameters(payload: object) -> None:
    with pytest.raises(ValueError):
        discussion_window.parse_discussion_action(json.dumps(payload))


def test_javascript_serialization_keeps_untrusted_text_as_json_data() -> None:
    payload = {"text": '"; alert(1); //\n</script>'}

    script = discussion_window.serialize_javascript_call("discussionApplyError", payload)
    encoded = script.removeprefix("window.discussionApplyError(").removesuffix(")")

    assert json.loads(encoded) == payload
    assert script.startswith("window.discussionApplyError(")


def test_event_batch_adds_snapshot_streaming_metadata_without_mutation() -> None:
    events = [
        {
            "session_id": "session",
            "event_seq": 1,
            "kind": "turn_started",
            "participant_id": "codex",
            "turn_id": "turn",
            "payload": {"round_index": 1},
        }
    ]
    snapshot = {
        "turns": [
            {
                "id": "turn",
                "supports_token_stream": False,
            }
        ]
    }

    script = discussion_window.serialize_event_batch(events, snapshot)
    encoded = script.removeprefix("window.discussionApplyEvents(").removesuffix(")")
    result = json.loads(encoded)

    assert result[0]["payload"]["supports_token_stream"] is False
    assert events[0]["payload"] == {"round_index": 1}


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_dispatches_start_and_stop_actions() -> None:
    bridge = FakeBridge()
    controller = discussion_window.DiscussionWindowController(bridge=cast(Any, bridge))
    webview = FakeWebView()
    controller._attached = True
    controller._web_ready = True
    controller.webview = webview

    controller._receive_action(
        json.dumps(
            {
                "action": "discussion_start",
                "topic": "問題",
                "participants": ["claude", "codex"],
                "moderatorId": "codex",
                "workingDir": "/tmp/project",
            }
        )
    )
    controller._receive_action('{"action":"discussion_stop"}')

    assert bridge.started is not None
    assert bridge.started[0] == "問題"
    assert [cast(Any, participant).id for participant in bridge.started[1]] == [
        "claude",
        "codex",
    ]
    assert bridge.started[2] == "codex"
    assert bridge.started[3] == "/tmp/project"
    assert bridge.stop_count == 1
    assert any(script.startswith("window.discussionApplySnapshot(") for script in webview.scripts)


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_forwards_guidance_flag_and_submitted_text() -> None:
    bridge = FakeBridge()
    controller = discussion_window.DiscussionWindowController(bridge=cast(Any, bridge))
    controller._attached = True
    controller._web_ready = True
    controller.webview = FakeWebView()

    controller._receive_action(
        json.dumps(
            {
                "action": "discussion_start",
                "topic": "問題",
                "participants": ["claude", "codex"],
                "guidanceBetweenRounds": True,
            }
        )
    )
    controller._receive_action(
        json.dumps({"action": "discussion_submit_guidance", "text": "只談單機部署"})
    )
    controller._receive_action(
        json.dumps({"action": "discussion_submit_guidance", "text": ""})
    )

    assert bridge.guidance_between_rounds is True
    assert bridge.submitted_guidance == ["只談單機部署", ""]


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_start_carries_whitelisted_model_into_spec() -> None:
    bridge = FakeBridge()
    controller = discussion_window.DiscussionWindowController(bridge=cast(Any, bridge))
    webview = FakeWebView()
    controller._attached = True
    controller._web_ready = True
    controller.webview = webview

    controller._receive_action(
        json.dumps(
            {
                "action": "discussion_start",
                "topic": "x",
                "participants": ["claude", "codex"],
                "models": {"claude": "opus", "codex": None},
            }
        )
    )

    assert bridge.started is not None
    specs = bridge.started[1]
    assert [cast(Any, spec).id for spec in specs] == ["claude", "codex"]
    assert cast(Any, specs[0]).model == "opus"
    assert cast(Any, specs[1]).model is None


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_dispatches_clear_action() -> None:
    bridge = FakeBridge()
    controller = discussion_window.DiscussionWindowController(bridge=cast(Any, bridge))
    webview = FakeWebView()
    controller._attached = True
    controller._web_ready = True
    controller.webview = webview

    controller._receive_action('{"action":"discussion_clear"}')

    assert bridge.clear_count == 1
    assert any(
        script.startswith("window.discussionApplySnapshot(") for script in webview.scripts
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_clear_busy_applies_error_message() -> None:
    bridge = FakeBridge()
    bridge.clear_status = {"status": "busy"}
    controller = discussion_window.DiscussionWindowController(bridge=cast(Any, bridge))
    webview = FakeWebView()
    controller._attached = True
    controller._web_ready = True
    controller.webview = webview

    controller._receive_action('{"action":"discussion_clear"}')

    assert bridge.clear_count == 1
    assert any(
        script.startswith("window.discussionApplyError(") for script in webview.scripts
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_converts_bad_action_to_javascript_error() -> None:
    controller = discussion_window.DiscussionWindowController(
        bridge=cast(Any, FakeBridge()),
    )
    webview = FakeWebView()
    controller._attached = True
    controller._web_ready = True
    controller.webview = webview

    controller._receive_action('{"action":"discussion_start","topic":3}')

    assert len(webview.scripts) == 1
    assert webview.scripts[0].startswith("window.discussionApplyError(")
    assert "requires a string topic" in webview.scripts[0]


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_picks_and_clears_working_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected = str(tmp_path / "project")
    monkeypatch.setattr(discussion_window, "pick_folder", lambda: selected)
    controller = discussion_window.DiscussionWindowController(
        bridge=cast(Any, FakeBridge()),
    )
    webview = FakeWebView()
    controller._attached = True
    controller._web_ready = True
    controller.webview = webview

    controller._receive_action('{"action":"discussion_pick_folder"}')
    script_count = len(webview.scripts)
    monkeypatch.setattr(discussion_window, "pick_folder", lambda: None)
    controller._receive_action('{"action":"discussion_pick_folder"}')
    assert len(webview.scripts) == script_count
    controller._receive_action('{"action":"discussion_clear_folder"}')

    assert webview.scripts[-2:] == [
        discussion_window.serialize_javascript_call(
            "discussionApplyWorkingDir", selected
        ),
        discussion_window.serialize_javascript_call(
            "discussionApplyWorkingDir", None
        ),
    ]


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_restores_working_directory_on_attach(tmp_path: Path) -> None:
    selected = str(tmp_path / "project")
    controller = discussion_window.DiscussionWindowController(
        bridge=cast(Any, FakeBridge(selected)),
    )
    webview = FakeWebView()
    controller._attached = True
    controller._web_ready = True
    controller.webview = webview

    controller._apply_full_state()

    assert discussion_window.serialize_javascript_call(
        "discussionApplyWorkingDir", selected
    ) in webview.scripts


def test_html_uses_isolated_handler_and_safe_dynamic_dom() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    assert 'const HANDLER = "usageDiscussion"' in html
    assert "window.discussionApplyEvents" in html
    assert "window.discussionApplySnapshot" in html
    assert "window.discussionApplyDetection" in html
    assert "window.discussionApplyPersonas" in html
    assert 'event.kind === "consensus_counted"' in html
    assert "window.discussionApplyWorkingDir" in html
    assert "window.discussionApplyError" in html
    assert ".innerHTML" not in html
    assert "createElement" in html
    assert "textContent" in html
    assert "prefers-color-scheme" in html
    assert "event.session_id !== currentSessionId" in html
    assert "sequence <= latestEventSeq" in html
    assert "workingDirectoryPathEl.textContent" in html
    assert "workingDir: workingDirectory" in html
    assert "endOnConsensus: endOnConsensusEl.checked" in html
    assert "debateStyleHintEl.textContent" in html
    assert "payload.stances" in html
    assert "participantNameFromState(participantId)" in html
    assert "discussion_consensus_stance_${stance}" in html


def test_failed_turn_error_is_collapsed_with_first_line_summary() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    assert 'document.createElement("details")' in html
    assert 'document.createElement("summary")' in html
    assert "fullError.split(/\\r?\\n/, 1)[0]" in html
    assert "summaryText.textContent = firstLine" in html
    assert "summaryText.title = firstLine" in html
    assert "error.textContent = fullError" in html
    assert "details.open" not in html
    assert ".turn-error-summary-text" in html
    assert "text-overflow: ellipsis" in html


def test_participant_chips_use_project_icons_and_inline_agy_badge() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "border-radius: 12px" in html
    assert "--surface-raised" in html
    assert "--brand-claude-soft" in html
    assert "grid-template-columns: auto minmax(0, 1fr) auto auto auto" in html
    assert "flex-wrap: wrap" in html
    assert "const PARTICIPANT_ICON_URIS" in html
    assert '"{{CLAUDE_ICON}}"' in html
    assert '"{{CODEX_ICON}}"' in html
    assert "const AGY_BADGE" in html
    assert "const DEFAULT_PARTICIPANT_BADGE" in html
    assert 'document.createElement("img")' in html
    assert 'badge.className = "participant-badge"' in html
    assert 'image.className = "participant-badge-image"' in html
    assert 'image.alt = ""' in html
    assert 'document.createElementNS("http://www.w3.org/2000/svg", "svg")' in html
    assert 'badge.setAttribute("aria-hidden", "true")' in html
    assert "createPersonaSelect(id)" in html
    assert "personaSelect," in html
    assert "chip.append(checkbox, head)" in html
    assert "url(http" not in html


def test_discussion_html_injects_existing_project_icon_data_uris(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        discussion_window,
        "_data_uri",
        lambda name: f"data:image/webp;base64,{name}",
    )

    html = discussion_window._load_discussion_html("en")

    assert "{{CLAUDE_ICON}}" not in html
    assert "{{CODEX_ICON}}" not in html
    assert "data:image/webp;base64,claude.webp" in html
    assert "data:image/webp;base64,codex.webp" in html


@pytest.mark.parametrize(
    ("topic", "participant_count", "status", "expected"),
    [
        ("", 1, "IDLE", False),
        (" \n\t", 1, "COMPLETED", False),
        ("question", 0, "IDLE", False),
        ("question", 1, "IDLE", True),
        ("question", 2, "COMPLETED", True),
        ("question", 1, "PREPARING", False),
        ("question", 1, "ROUND1_RUNNING", False),
        ("question", 1, "ROUND2_RUNNING", False),
        ("question", 1, "SUMMARIZING", False),
        ("question", 1, "CANCELLING", False),
        ("question", 1, "FAILED", True),
    ],
)
def test_start_button_logic(
    topic: str,
    participant_count: int,
    status: str,
    expected: bool,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to evaluate the pure browser control function")
    html = HTML_PATH.read_text(encoding="utf-8")
    statuses = re.search(
        r"    const RUNNING_STATUSES = new Set\(\[.*?^    \]\);",
        html,
        flags=re.MULTILINE | re.DOTALL,
    )
    function = re.search(
        r"    function canStartDiscussion\(.*?^    \}",
        html,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert statuses is not None
    assert function is not None
    invocation = (
        f"{statuses.group(0)}\n{function.group(0)}\n"
        "process.stdout.write(JSON.stringify(canStartDiscussion("
        f"{json.dumps(topic)}, {participant_count}, {json.dumps(status)})));"
    )

    result = subprocess.run(
        [node, "-e", invocation],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) is expected


def test_checked_badge_host_is_never_a_replaced_element() -> None:
    """The ✓ overlay is an ::after on .participant-badge, which never renders on
    an <img>, so every branch must host it on a span with the icon nested."""
    html = HTML_PATH.read_text(encoding="utf-8")

    assert ".participant-chip:has(input:checked) .participant-badge::after" in html
    assert 'badge.className = "participant-badge";\n        badge.setAttribute(' in html
    assert "badge.append(image);" in html
    assert 'badge.className = "participant-badge";\n        badge.alt' not in html
    assert 'document.createElement("img");\n        badge.className' not in html


@pytest.mark.parametrize(
    ("topic", "participant_count", "status", "expected"),
    [
        ("", 1, "IDLE", "discussion_start_hint_topic"),
        (" \n\t", 0, "ROUND1_RUNNING", "discussion_start_hint_topic"),
        ("question", 0, "IDLE", "discussion_start_hint_participants"),
        ("question", 1, "PREPARING", "discussion_start_hint_running"),
        ("question", 1, "SUMMARIZING", "discussion_start_hint_running"),
        ("question", 1, "IDLE", ""),
        ("question", 2, "COMPLETED", ""),
        ("question", 1, "FAILED", ""),
    ],
)
def test_start_hint_explains_why_start_is_disabled(
    topic: str,
    participant_count: int,
    status: str,
    expected: str,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to evaluate the pure browser control function")
    html = HTML_PATH.read_text(encoding="utf-8")
    statuses = re.search(
        r"    const RUNNING_STATUSES = new Set\(\[.*?^    \]\);",
        html,
        flags=re.MULTILINE | re.DOTALL,
    )
    function = re.search(
        r"    function startHintKey\(.*?^    \}",
        html,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert statuses is not None
    assert function is not None
    invocation = (
        f"{statuses.group(0)}\n{function.group(0)}\n"
        "process.stdout.write(JSON.stringify(startHintKey("
        f"{json.dumps(topic)}, {participant_count}, {json.dumps(status)})));"
    )

    result = subprocess.run(
        [node, "-e", invocation],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == expected


def test_start_hint_is_wired_to_the_start_button() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    assert '<div class="start-hint" id="start-hint" role="status" hidden></div>' in html
    assert 'aria-describedby="start-hint"' in html
    assert 'startHintEl.textContent = startHint ? t(startHint) : "";' in html
    assert "startHintEl.hidden = !startHint;" in html


def test_moderator_toggle_exposes_pressed_state() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    assert 'moderator.setAttribute("aria-pressed", isModerator ? "true" : "false");' in html
    assert '"discussion_moderator_current" : "discussion_moderator_set"' in html


def test_persona_picker_groups_packs_in_source_order_and_puts_other_last() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to evaluate persona picker grouping")
    html = HTML_PATH.read_text(encoding="utf-8")
    function = re.search(
        r"    function buildPersonaGroups\(\) \{.*?^    \}",
        html,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert function is not None
    personas = [
        {"id": "a1", "name": "A1", "persona_name": "One", "pack_name": "Alpha"},
        {"id": "other", "name": "Other role", "persona_name": "", "pack_name": ""},
        {"id": "b1", "name": "B1", "persona_name": "", "pack_name": "Beta"},
        {"id": "a2", "name": "A2", "persona_name": "Two", "pack_name": "Alpha"},
    ]
    invocation = f"""
const personas = {json.dumps(personas)};
const t = (key) => key === "discussion_persona_other" ? "Other" : key;
{function.group(0)}
process.stdout.write(JSON.stringify(buildPersonaGroups().map((group) => ({{
  label: group.label,
  ids: group.items.map((item) => item.id),
}}))));
"""

    result = subprocess.run(
        [node, "-e", invocation],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == [
        {"label": "Alpha", "ids": ["a1", "a2"]},
        {"label": "Beta", "ids": ["b1"]},
        {"label": "Other", "ids": ["other"]},
    ]
    assert 'neutral.textContent = t("discussion_persona_neutral")' in html
    assert 'header.className = "persona-menu-group-toggle"' in html
    assert 'indicator.className = "persona-menu-group-indicator"' in html
    assert 'trigger.setAttribute("aria-label", t("discussion_persona"))' in html


def test_persona_picker_uses_fixed_body_popup_and_closes_before_render() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    styles = html.split("<style>", 1)[1].split("</style>", 1)[0]
    trigger_function = re.search(
        r"    function createPersonaSelect\(id\) \{.*?^    \}",
        html,
        re.MULTILINE | re.DOTALL,
    )
    menu_style = re.search(r"    \.persona-menu \{.*?^    \}", styles, re.MULTILINE | re.DOTALL)
    option_style = re.search(
        r"    \.persona-menu-option \{.*?^    \}",
        styles,
        re.MULTILINE | re.DOTALL,
    )
    group_style = re.search(
        r"    \.persona-menu-group-toggle \{\n      justify-content:.*?^    \}",
        styles,
        re.MULTILINE | re.DOTALL,
    )

    assert trigger_function is not None
    assert 'document.createElement("button")' in trigger_function.group(0)
    assert 'document.createElement("select")' not in trigger_function.group(0)
    assert menu_style is not None
    assert "position: fixed" in menu_style.group(0)
    assert "overflow-y: auto" in menu_style.group(0)
    assert option_style is not None
    assert "font-size: 14px" in option_style.group(0)
    assert group_style is not None
    assert "font-size: 12px" in group_style.group(0)
    assert "document.body.append(menu)" in html
    assert "availableBelow < desiredHeight" in html
    assert 'menu.dataset.placement = openUpward ? "top" : "bottom"' in html
    assert "function render() {\n      closePersonaMenu();" in html
    assert 'event.key === "ArrowDown"' in html
    assert '"ArrowUp"' in html
    assert 'event.key === "Escape"' in html
    assert 'event.key !== "Enter" && event.key !== " "' in html
    assert 'document.addEventListener("pointerdown"' in html
    assert 'neutral.className = "persona-menu-option persona-menu-neutral"' in html
    assert "const expanded = group.items.some" in html
    assert "focusTarget.scrollIntoView" in html


def test_persona_picker_positions_above_when_below_space_is_insufficient() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to evaluate persona picker positioning")
    html = HTML_PATH.read_text(encoding="utf-8")
    function = re.search(
        r"    function positionPersonaMenu\(trigger, menu\) \{.*?^    \}",
        html,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert function is not None
    invocation = f"""
const window = {{ innerWidth: 800, innerHeight: 600 }};
{function.group(0)}
function place(rect) {{
  const trigger = {{ getBoundingClientRect: () => rect }};
  const menu = {{ scrollHeight: 300, style: {{}}, dataset: {{}} }};
  positionPersonaMenu(trigger, menu);
  return {{ placement: menu.dataset.placement, top: menu.style.top }};
}}
process.stdout.write(JSON.stringify({{
  nearTop: place({{ top: 100, bottom: 130, right: 700, width: 128 }}),
  nearBottom: place({{ top: 500, bottom: 530, right: 700, width: 128 }}),
}}));
"""

    result = subprocess.run(
        [node, "-e", invocation],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "nearTop": {"placement": "bottom", "top": "134px"},
        "nearBottom": {"placement": "top", "top": "196px"},
    }


def test_html_controls_and_history_follow_use_reviewed_logic() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "function canStartDiscussion(topic, participantCount, status)" in html
    assert "startEl.disabled = !canStartDiscussion(" in html
    assert "stopEl.disabled = !running" in html
    assert "PARTICIPANT_IDS.filter((id) => selected.has(id))" in html
    assert "function isHistoryNearBottom()" in html
    assert "return distance < 80" in html
    assert "if (wasNearBottom && shouldFollow)" in html
    assert "scrollHistoryToBottom()" in html
    assert "historyEl.scrollTop = previousScrollTop" in html


def test_moderator_chip_keeps_existing_start_payload_and_rejects_unavailable() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "moderatorId: moderatorId || null" in html
    assert "moderator.disabled = !available || !selected.has(id) || isRunning();" in html
    assert "if (!available || !selected.has(id) || isRunning()) return;" in html


def test_html_colors_are_tokenized_with_light_mode_overrides() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    styles = html.split("<style>", 1)[1].split("</style>", 1)[0]

    assert "@media (prefers-color-scheme: light)" in styles
    assert "@media (prefers-color-scheme: dark)" not in styles
    assert "color: white" not in styles
    assert "background: transparent" not in styles


def test_copy_feedback_uses_i18n_and_four_section_plain_text() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    assert "function summaryForClipboard()" in html
    assert "SUMMARY_HEADINGS.map" in html
    assert 't("discussion_copied")' in html
    assert 't("discussion_copy_failed")' in html
    assert "JSON.stringify(summaryText)" not in html


def test_running_summary_stays_hidden_until_labels_are_restored() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    assert 'summaryTurn.status === "DONE"' in html
    assert '!["DONE", "FAILED"].includes(summaryTurn.status)' in html


def test_html_visible_static_elements_use_i18n_keys() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    for key in (
        "discussion_topic_label",
        "discussion_topic_placeholder",
        "discussion_attach_image",
        "discussion_participants",
        "discussion_moderator",
        "discussion_persona",
        "discussion_persona_neutral",
        "discussion_persona_other",
        "discussion_debate_style",
        "discussion_consensus_count_summary",
        "discussion_end_on_consensus",
        "discussion_consensus_early_exit",
        "discussion_working_directory",
        "discussion_pick_folder",
        "discussion_clear_folder",
        "discussion_working_directory_none",
        "discussion_working_directory_warning",
        "discussion_start",
        "discussion_stop",
        "discussion_history",
        "discussion_summary",
        "discussion_copy",
    ):
        assert f'"{key}"' in html
    parser = VisibleMarkupTextParser()
    parser.feed(html)
    assert parser.text == []


def test_consensus_controls_and_usage_caps_are_translated_in_all_languages() -> None:
    bundle = json.loads(I18N_PATH.read_text(encoding="utf-8"))
    cap_markers = {
        "zh-TW": "最多",
        "zh-CN": "最多",
        "en": "up to",
        "ja": "最大",
        "ko": "최대",
    }

    for language, marker in cap_markers.items():
        translations = bundle[language]
        assert translations["discussion_end_on_consensus"]
        assert "{round}" in translations["discussion_consensus_early_exit"]
        assert marker in translations["discussion_estimate_tokens"]
        for style in (
            "constructive",
            "adversarial",
            "collaborative",
            "socratic",
            "devils_advocate",
        ):
            assert translations[f"discussion_debate_style_{style}_hint"]
        for stance in ("agree", "disagree", "alternative", "unparsed"):
            assert translations[f"discussion_consensus_stance_{stance}"]


def test_window_source_keeps_bridge_logic_out_and_main_thread_drain_batched() -> None:
    source = Path(discussion_window.__file__).read_text(encoding="utf-8")

    assert "class _DiscussionWindow(NSWindow)" in source
    assert "def canBecomeMainWindow" in source
    assert "def canBecomeKeyWindow" in source
    assert "drain_events(50)" in source
    assert "evaluateJavaScript_completionHandler_" in source
    assert "run_streaming" not in source
    assert "subprocess" not in source
    assert "build_round1_prompt" not in source


def test_build_attachment_name_uses_timestamp_and_index() -> None:
    assert (
        discussion_window.build_attachment_name("20260724-185530", 1, ".png")
        == "20260724-185530-1.png"
    )
    assert (
        discussion_window.build_attachment_name("20260724-185530", 12, ".jpg")
        == "20260724-185530-12.jpg"
    )


def test_prune_attachments_keeps_newest_fifty(tmp_path: Path) -> None:
    directory = tmp_path / "attachments"
    directory.mkdir()
    for index in range(55):
        entry = directory / f"2026010{index // 10}-00000{index % 10}-{index}.png"
        entry.write_bytes(b"x")
        stat = entry.stat()
        os.utime(entry, (stat.st_atime, 1_000_000 + index))

    discussion_window.prune_attachments(directory=directory, keep=50)

    remaining = sorted(directory.iterdir(), key=lambda path: path.name)
    assert len(remaining) == 50
    remaining_indexes = {
        int(path.name.rsplit("-", 1)[1].split(".", 1)[0]) for path in remaining
    }
    assert remaining_indexes == set(range(5, 55))


def test_save_attachment_bytes_writes_timestamped_names_and_prunes(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "attachments"
    first = discussion_window.save_attachment_bytes(b"data", ".png", directory=directory)
    second = discussion_window.save_attachment_bytes(b"data", ".png", directory=directory)

    assert first.is_file() and second.is_file()
    assert first.parent == directory
    if sys.platform != "win32":  # POSIX file modes; Windows chmod only toggles the read-only bit
        assert first.stat().st_mode & 0o777 == 0o600
        assert directory.stat().st_mode & 0o777 == 0o700
    assert re.fullmatch(r"\d{8}-\d{6}-\d+\.png", first.name)
    assert second != first


def test_import_attachment_file_copies_supported_rejects_others(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "attachments"
    src = tmp_path / "screen.png"
    src.write_bytes(b"png")
    unsupported = tmp_path / "notes.txt"
    unsupported.write_bytes(b"text")

    copied = discussion_window.import_attachment_file(str(src), directory=directory)
    assert copied is not None
    assert copied.is_file()
    assert copied.parent == directory
    assert copied.read_bytes() == b"png"
    if sys.platform != "win32":  # POSIX file modes; Windows chmod only flips read-only
        assert copied.stat().st_mode & 0o777 == 0o600
        assert directory.stat().st_mode & 0o777 == 0o700

    assert (
        discussion_window.import_attachment_file(str(unsupported), directory=directory)
        is None
    )
    assert (
        discussion_window.import_attachment_file(
            str(tmp_path / "missing.png"), directory=directory
        )
        is None
    )


@pytest.mark.parametrize(
    "raw",
    [
        '{"action":"discussion_paste_image"}',
        '{"action":"discussion_pick_image"}',
    ],
)
def test_parse_simple_attachment_actions(raw: str) -> None:
    assert (
        discussion_window.parse_discussion_action(raw).action
        == json.loads(raw)["action"]
    )


def test_parse_remove_attachment_requires_string_path() -> None:
    parsed = discussion_window.parse_discussion_action(
        json.dumps(
            {"action": "discussion_remove_attachment", "path": "/tmp/x.png"}
        )
    )
    assert parsed.action == "discussion_remove_attachment"
    assert parsed.attachment_path == "/tmp/x.png"


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "discussion_remove_attachment"},
        {"action": "discussion_remove_attachment", "path": ""},
        {"action": "discussion_remove_attachment", "path": 3},
    ],
)
def test_parse_remove_attachment_rejects_bad_path(payload: object) -> None:
    with pytest.raises(ValueError):
        discussion_window.parse_discussion_action(json.dumps(payload))


def test_parse_start_action_carries_attachments() -> None:
    parsed = discussion_window.parse_discussion_action(
        json.dumps(
            {
                "action": "discussion_start",
                "topic": "問題",
                "participants": ["claude"],
                "attachments": ["/tmp/a.png", "/tmp/b.jpg"],
            }
        )
    )
    assert parsed.attachments == ("/tmp/a.png", "/tmp/b.jpg")


def test_parse_start_rejects_non_string_attachments() -> None:
    with pytest.raises(ValueError):
        discussion_window.parse_discussion_action(
            json.dumps(
                {
                    "action": "discussion_start",
                    "topic": "x",
                    "participants": ["claude"],
                    "attachments": ["/tmp/a.png", 3],
                }
            )
        )


def _attachments_controller(bridge: object) -> Any:
    controller = discussion_window.DiscussionWindowController(bridge=cast(Any, bridge))
    webview = FakeWebView()
    controller._attached = True
    controller._web_ready = True
    controller.webview = webview
    return controller


def _last_attachment_payload(scripts: list[str]) -> dict[str, object]:
    matches = [
        script
        for script in scripts
        if script.startswith("window.discussionApplyAttachments(")
    ]
    assert matches
    encoded = matches[-1].removeprefix("window.discussionApplyAttachments(").removesuffix(")")
    return cast(dict[str, object], json.loads(encoded))


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_paste_image_saves_attachment_and_applies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    saved = tmp_path / "20260724-185530-1.png"
    monkeypatch.setattr(
        discussion_window, "read_pasteboard_image", lambda: (b"png", ".png")
    )
    monkeypatch.setattr(
        discussion_window,
        "save_attachment_bytes",
        lambda data, suffix, directory=discussion_window.ATTACHMENTS_DIR: saved,
    )
    controller = _attachments_controller(FakeBridge())

    controller._receive_action('{"action":"discussion_paste_image"}')

    assert controller._attachments == [{"name": saved.name, "path": str(saved)}]
    payload = _last_attachment_payload(controller.webview.scripts)
    assert payload["attachments"] == [{"name": saved.name, "path": str(saved)}]
    assert payload["hint"] is None


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_paste_without_image_reports_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discussion_window, "read_pasteboard_image", lambda: None)
    controller = _attachments_controller(FakeBridge())

    controller._receive_action('{"action":"discussion_paste_image"}')

    assert controller._attachments == []
    payload = _last_attachment_payload(controller.webview.scripts)
    assert payload["hint"]


def test_parse_drop_image_carries_data_and_name() -> None:
    parsed = discussion_window.parse_discussion_action(
        json.dumps(
            {"action": "discussion_drop_image", "data": "cG5n", "name": "x.png"}
        )
    )
    assert parsed.action == "discussion_drop_image"
    assert parsed.attachment_data == "cG5n"
    assert parsed.attachment_name == "x.png"


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "discussion_drop_image", "name": "x.png"},
        {"action": "discussion_drop_image", "data": "cG5n"},
        {"action": "discussion_drop_image", "data": "", "name": "x.png"},
        {"action": "discussion_drop_image", "data": "cG5n", "name": " "},
        {"action": "discussion_drop_image", "data": 3, "name": "x.png"},
        {"action": "discussion_drop_image", "data": "cG5n", "name": None},
    ],
)
def test_parse_drop_image_rejects_bad_fields(payload: object) -> None:
    with pytest.raises(ValueError):
        discussion_window.parse_discussion_action(json.dumps(payload))


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_drop_image_decodes_and_saves_attachment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    saved = tmp_path / "20260724-185530-1.png"
    captured: dict[str, object] = {}

    def fake_save(
        data: bytes,
        suffix: str,
        directory: Path = discussion_window.ATTACHMENTS_DIR,
    ) -> Path:
        captured["data"] = data
        captured["suffix"] = suffix
        return saved

    monkeypatch.setattr(discussion_window, "save_attachment_bytes", fake_save)
    controller = _attachments_controller(FakeBridge())

    controller._receive_action(
        json.dumps(
            {
                "action": "discussion_drop_image",
                "data": base64.b64encode(b"png").decode(),
                "name": "screen.png",
            }
        )
    )

    assert captured == {"data": b"png", "suffix": ".png"}
    assert controller._attachments == [{"name": saved.name, "path": str(saved)}]
    payload = _last_attachment_payload(controller.webview.scripts)
    assert payload["attachments"] == [{"name": saved.name, "path": str(saved)}]
    assert payload["hint"] is None


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_drop_non_image_suffix_reports_hint() -> None:
    controller = _attachments_controller(FakeBridge())

    controller._receive_action(
        json.dumps(
            {
                "action": "discussion_drop_image",
                "data": base64.b64encode(b"text").decode(),
                "name": "notes.txt",
            }
        )
    )

    assert controller._attachments == []
    payload = _last_attachment_payload(controller.webview.scripts)
    assert payload["hint"]


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_pick_image_imports_attachment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    src = tmp_path / "source.png"
    src.write_bytes(b"png")
    copied = tmp_path / "attachments" / "20260724-185530-1.png"
    copied.parent.mkdir()
    monkeypatch.setattr(discussion_window, "pick_image_file", lambda: str(src))
    monkeypatch.setattr(
        discussion_window,
        "import_attachment_file",
        lambda path, directory=discussion_window.ATTACHMENTS_DIR: copied,
    )
    controller = _attachments_controller(FakeBridge())

    controller._receive_action('{"action":"discussion_pick_image"}')

    assert controller._attachments == [{"name": copied.name, "path": str(copied)}]


@pytest.mark.skipif(sys.platform != "darwin", reason="PyObjC action shell is macOS-only")
def test_controller_remove_attachment_deletes_file(tmp_path: Path) -> None:
    target = tmp_path / "20260724-185530-1.png"
    target.write_bytes(b"png")
    controller = _attachments_controller(FakeBridge())
    controller._attachments = [{"name": target.name, "path": str(target)}]

    controller._receive_action(
        json.dumps({"action": "discussion_remove_attachment", "path": str(target)})
    )

    assert controller._attachments == []
    assert not target.exists()
