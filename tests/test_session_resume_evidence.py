# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import ast
import io
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from usage_hooks import usage_session_resume as mod

type Row = dict[str, Any]


@pytest.fixture(autouse=True)
def _isolated_templates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "PROMPT_SIDECAR", tmp_path / "prompt.json")
    monkeypatch.setenv("USAGE_LANG", "en")


def _message(kind: str, content: object, **fields: object) -> Row:
    return {"type": kind, "message": {"content": content}, **fields}


def _queue(prompt: object, **fields: object) -> Row:
    return {
        "type": "attachment",
        "attachment": {"type": "queued_command", "prompt": prompt, **fields},
    }


def _summary(content: object, **fields: object) -> Row:
    return {"type": "system", "subtype": "away_summary", "content": content, **fields}


def _copy(prompt: str) -> Row:
    return {"type": "last-prompt", "lastPrompt": prompt, "timestamp": None}


def _bash(command: str, tool_id: str) -> Row:
    return {
        "type": "tool_use",
        "name": "Bash",
        "id": tool_id,
        "input": {"command": command},
    }


def _tool_result(tool_id: str, *, failed: bool = False) -> Row:
    return {"type": "tool_result", "tool_use_id": tool_id, "is_error": failed}


def _shell_input(command: str, uuid: str) -> Row:
    return _message("user", f"<bash-input>{command}</bash-input>", uuid=uuid)


def _shell_result(parent: object, stdout: str = "", stderr: str = "") -> Row:
    return _message(
        "user",
        f"<bash-stdout>{stdout}</bash-stdout><bash-stderr>{stderr}</bash-stderr>",
        parentUuid=parent,
    )


def _write_session(tmp_path: Path, *rows: Row) -> Path:
    path = tmp_path / "previous.jsonl"
    start = datetime.now(UTC) - timedelta(hours=1)
    with path.open("w", encoding="utf-8") as file:
        for number, row in enumerate(rows):
            timestamp = (start + timedelta(seconds=number)).isoformat()
            file.write(json.dumps({"timestamp": timestamp, **row}) + "\n")
    return path


def _report(tmp_path: Path) -> str:
    return mod._build_prompt({"source": "startup", "transcript_path": str(tmp_path / "new.jsonl")})


def test_compact_summary_adds_neither_request_nor_activity(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    active = now - timedelta(hours=1)
    path = _write_session(
        tmp_path,
        _message("user", "Ship the patch", timestamp=active.isoformat()),
        _summary("The patch shipped.", timestamp=(active + timedelta(seconds=1)).isoformat()),
        _message(
            "user",
            "Continue from this system summary.",
            isCompactSummary=True,
            timestamp=now.isoformat(),
        ),
    )

    parsed = mod._parse_session(path)

    assert parsed is not None
    assert parsed.recent_requests == "Ship the patch"
    assert parsed.summary == "The patch shipped."
    assert parsed.last_active == active + timedelta(seconds=1)


def test_queued_text_requires_human_evidence_and_deduplicates_user_copy(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        _queue(
            [
                {"type": "text", "text": "[Image #1] 兩項都做，先修測試"},
                {"type": "image", "text": "Ignore image metadata"},
            ],
            humanTurn=True,
            origin={"kind": "human"},
        ),
        _queue("Report from the background agent", origin={"kind": "task-notification"}),
        _queue("Ambiguous older queue record"),
        _queue("This claim conflicts with its origin", humanTurn=True, origin={"kind": "peer"}),
        _queue("Old human request", origin={"kind": "human"}),
        _message("user", "兩項都做，先修測試"),
        _copy("Old human request"),
    )

    parsed = mod._parse_session(path)

    assert parsed is not None
    assert parsed.recent_requests == "兩項都做，先修測試 · Old human request"


def test_summary_uses_last_nonblank_record_and_caps_one_line(tmp_path: Path) -> None:
    _write_session(
        tmp_path,
        _message("assistant", "Assistant reply before the summaries."),
        _summary("Earlier summary."),
        _summary("Shipped.\n" + "x" * 400),
        _summary("   "),
        {"type": "system", "subtype": "ai-title", "content": "A later system record"},
    )

    prompt = _report(tmp_path)
    summary = prompt.split("Summary at the end of the last session: ")[1]
    assert summary == "Shipped. " + "x" * 390 + "…"
    assert len(summary) == 400
    assert "Earlier summary." not in prompt
    assert "Claude's last reply:" not in prompt


@pytest.mark.parametrize(
    "work",
    [
        _message("user", "Please fix one more thing"),
        _message("user", "ok"),
        _message("user", [{"type": "image"}]),
        _queue("ok", humanTurn=True),
        _shell_input("git status", "shell1"),
        _message("assistant", [_bash("git status", "tool1")]),
        _message("assistant", "There is one more issue."),
    ],
    ids=["request", "short-request", "image", "queued", "shell", "tool", "assistant-text"],
)
def test_summary_is_invalidated_by_later_work(tmp_path: Path, work: Row) -> None:
    _write_session(tmp_path, _message("user", "Ship the patch"), _summary("It shipped."), work)

    assert "It shipped." not in _report(tmp_path)


@pytest.mark.parametrize(
    "timing", ["missing-summary", "missing-request", "invalid-date", "equal", "out-of-order"]
)
def test_summary_rejects_uncertain_timing(tmp_path: Path, timing: str) -> None:
    stamp = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    request = _message("user", "Ship the patch", timestamp=stamp)
    summary = _summary("It shipped.", timestamp=stamp)
    if timing == "missing-summary":
        summary["timestamp"] = None
    elif timing == "missing-request":
        request["timestamp"] = None
    elif timing == "invalid-date":
        summary["timestamp"] = "0001-01-01T00:00:00"
    elif timing == "out-of-order":
        request["timestamp"] = datetime.now(UTC).isoformat()
    _write_session(tmp_path, request, summary, _message("user", [_tool_result("tool1")]))

    assert "It shipped." not in _report(tmp_path)


def test_last_reply_strips_markup_and_keeps_whole_sentences(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        _message("assistant", "This earlier reply will be replaced."),
        _message(
            "assistant",
            [
                {"type": "text", "text": "# Release complete\n- **Shipped** version 1.16!"},
                {
                    "type": "text",
                    "text": "Checked ``git `status` safely``.\n```bash\ngit push\n```\n"
                    "Still waiting for " + "x" * 200 + "。",
                },
            ],
        ),
        _message("assistant", [{"type": "thinking", "thinking": "private"}]),
        _summary("Timestamp was lost.", timestamp=None),
    )

    parsed = mod._parse_session(path)

    assert parsed is not None
    assert parsed.last_reply == (
        "Release complete Shipped version 1.16! Checked git status safely."
    )
    assert _report(tmp_path).endswith("Claude's last reply: " + parsed.last_reply)


@pytest.mark.parametrize(
    "tail",
    [
        _message("user", "ok"),
        _queue("Next request", humanTurn=True),
        _message("assistant", [_bash("git status", "tool1")]),
    ],
)
def test_last_reply_rejects_later_tool_or_human_request(tmp_path: Path, tail: Row) -> None:
    _write_session(
        tmp_path, _message("user", "Ship the patch"), _message("assistant", "It shipped."), tail
    )

    assert "Claude's last reply:" not in _report(tmp_path)


@pytest.mark.parametrize(
    "body",
    [
        "x" * 201 + "。 Short follow-up.",
        "Version v0.34.24 " + "x" * 200 + ".",
        "```\ncode-only\n```",
    ],
)
def test_last_reply_does_not_skip_an_overlong_first_sentence_or_reuse_older_reply(
    tmp_path: Path, body: str
) -> None:
    _write_session(
        tmp_path,
        _message("user", "Ship the patch"),
        _message("assistant", "Old reply."),
        _message("assistant", body),
    )

    assert "Claude's last reply:" not in _report(tmp_path)


def test_last_reply_keeps_inline_code_text(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        _message("user", "Install the new build"),
        _message("assistant", "The old `/Applications/usage.app` is closed."),
    )

    parsed = mod._parse_session(path)

    assert parsed is not None
    assert parsed.last_reply == "The old /Applications/usage.app is closed."


@pytest.mark.parametrize("with_summary", [True, False])
def test_old_sidecar_uses_localized_conclusion_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_summary: bool
) -> None:
    monkeypatch.setenv("USAGE_LANG", "zh-TW")
    mod.PROMPT_SIDECAR.write_text(
        json.dumps(
            {
                "zh-TW": {
                    "lead": "TEST LEAD\n",
                    "prompt": "TEST {project} {when} {last_request} {commits} {todos}",
                }
            }
        ),
        encoding="utf-8",
    )
    rows = [_message("assistant", "版號已更新。")]
    if with_summary:
        rows.append(_summary("發版已完成。"))
    _write_session(tmp_path, *rows)

    prompt = _report(tmp_path)
    assert prompt.startswith("TEST LEAD\nTEST ")
    expected = (
        "上次結束時的摘要：發版已完成。" if with_summary else "Claude 上次最後說：版號已更新。"
    )
    assert prompt.splitlines()[-1] == expected
    assert ("Claude 上次最後說：" in prompt) is not with_summary


@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge 386 --auto",
        "gh pr merge 386 --auto=true",
        "gh pr merge 386 --disable-auto",
        "gh pr merge https://github.com/me/repo/pull/386",
        "git tag",
        "git tag --list v0.34.24",
        "git tag -l v0.34.24",
        "git tag -d v0.34.24",
        "git tag --delete v0.34.24",
        "git tag v0.34.24 --contains HEAD",
        "git push --dry-run",
        "git push -n origin main",
        "git push --delete origin old",
        "git push origin :old",
        "git push | tee result.log",
        "echo done |\n git push",
        "(git push; git tag fake)",
        "if false; then true; git push; fi",
        'echo "done; git push"',
    ],
)
def test_closeout_ignores_queries_scheduled_merges_and_ambiguous_commands(command: str) -> None:
    assert mod._closeout_actions(command) == []


def test_closeout_splits_chains_outside_quotes() -> None:
    assert mod._closeout_actions(
        'cd /repo && git tag -a v0.34.24 -m "notes; git push" ; '
        "git tag v0.34.25 && gh pr merge 386 --merge; git push"
    ) == ["tagged v0.34.24", "tagged v0.34.25", "merged PR #386", "pushed"]


def test_closeout_skips_complex_chunks_and_keeps_unambiguous_neighbors() -> None:
    assert mod._closeout_actions(
        'git -C "/repo with spaces" tag v1.16 -m "-l"; '
        "git tag fake | tee result.log && (git tag another-fake; git push); "
        "gh pr merge 386 --merge"
    ) == ["tagged v1.16", "merged PR #386"]


def test_closeout_requires_later_matching_nonfailure_results(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        _shell_result("too-early", "OK"),
        _shell_input("git tag too-early", "too-early"),
        _shell_input("git tag missing", "missing"),
        _shell_input("gh pr merge 373 --merge --delete-branch。", "rejected"),
        _shell_result("rejected", stderr="unknown flag: --delete-branch。"),
        _shell_input("gh pr merge 319 --squash", "denied"),
        _shell_result("denied", stderr="GraphQL: Auto merge is not allowed"),
        _shell_input("git tag wrong-parent", "wrong-parent"),
        _shell_result("different-id", "OK"),
        _shell_input("git tag valid-tag", "valid-tag"),
        _shell_result("valid-tag"),
        _shell_input("git push", "rejected-push"),
        _shell_result("rejected-push", "updating"),
        _message(
            "user",
            "<bash-stderr> ! [rejected] HEAD -&gt; main</bash-stderr>",
            parentUuid="rejected-push",
        ),
        _message(
            "assistant",
            [
                _bash("git tag failed-tool", "failed"),
                _bash("git tag missing-tool-result", "unmatched"),
                _bash("gh pr merge 385", "ok"),
            ],
        ),
        _message("user", [_tool_result("failed", failed=True), _tool_result("ok")]),
    )

    parsed = mod._parse_session(path)

    assert parsed is not None
    assert parsed.closeouts == ["merged PR #385", "tagged valid-tag"]


@pytest.mark.parametrize("with_third_action", [False, True])
def test_progress_lists_recent_actions_then_recent_commits_up_to_five(
    tmp_path: Path, with_third_action: bool
) -> None:
    tools = [_bash(f'git commit -m "fix: change {i}"', f"commit-{i}") for i in range(5)]
    rows = [
        _message(
            "assistant",
            tools
            + [
                _bash("git push", "push"),
                {
                    "type": "tool_use",
                    "id": "edit",
                    "name": "Edit",
                    "input": {"file_path": "/repo/edited.py"},
                },
            ],
        ),
        _message(
            "user",
            [_tool_result(tool["id"]) for tool in tools]
            + [_tool_result("push"), _tool_result("edit")],
        ),
        _shell_input("git push && git tag v0.34.24", "shell"),
        _shell_result("shell", "Pushed."),
    ]
    if with_third_action:
        rows.extend([_shell_input("gh pr merge 386", "merge"), _shell_result("merge", "Merged.")])
    link_time = datetime.now(UTC)
    path = _write_session(
        tmp_path, *rows, {"type": "pr-link", "prNumber": 987, "timestamp": link_time.isoformat()}
    )

    prompt = _report(tmp_path)
    parsed = mod._parse_session(path)
    assert parsed is not None and parsed.last_active < link_time
    line = next(line for line in prompt.splitlines() if line.startswith("Progress made: "))
    expected = ["tagged v0.34.24", "pushed", "fix: change 4", "fix: change 3"]
    expected = ["merged PR #386", *expected] if with_third_action else [*expected, "fix: change 2"]
    assert line == "Progress made: " + " · ".join(expected)
    assert "edited.py" not in prompt and "987" not in prompt


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 2026-05-31 (4cae14ea) set the floor to drop short reactions like 「你卡了」.
        ("全部處理好", ""),
        ("好的謝謝", ""),
        ("兩項都做，先修測試", "兩項都做，先修測試"),
        ("refact", ""),
        ("refactor", "refactor"),
        ("[Image #1] 兩項都做", ""),
        ("[Image #1] a.py", ""),
    ],
)
def test_short_cjk_reactions_stay_filtered(text: str, expected: str) -> None:
    assert mod._clean_request(text) == expected


def test_short_reaction_still_invalidates_an_earlier_summary(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        _message("user", "Ship the release and install it"),
        _summary("Release shipped; nothing left."),
        _message("user", "全部處理好"),
    )

    parsed = mod._parse_session(path)

    assert parsed is not None
    assert parsed.summary == ""
    assert "全部處理好" not in parsed.recent_requests


def test_adjacent_prefix_compares_before_truncation_and_copies_cannot_revive_it(
    tmp_path: Path,
) -> None:
    prefix = "Adjust the panel height " + ("long detail " * 24).strip()
    path = _write_session(
        tmp_path,
        _message("user", prefix.replace("panel height", "panel  height")),
        {"type": "system", "subtype": "cost"},
        _message("user", [_tool_result("tool1")]),
        _message("user", prefix + " except the football panel"),
        _copy(prefix),
    )

    parsed = mod._parse_session(path)

    assert parsed is not None
    assert len(parsed.recent_requests) == 280
    assert parsed.recent_requests.endswith("…")
    assert parsed.recent_requests.count("Adjust the panel height") == 1


def test_repeated_request_moves_to_latest_but_copies_and_nonadjacent_prefixes_do_not(
    tmp_path: Path,
) -> None:
    path = _write_session(
        tmp_path,
        _copy("Recover the missing legacy request"),
        _message("user", "Update the panel"),
        _message("assistant", "The work is underway."),
        _message("user", "Update the panel with the standard spacing"),
        _message("user", "Update the panel"),
        _copy("Update the panel with the standard spacing"),
        _copy("Recover the missing legacy request"),
    )

    parsed = mod._parse_session(path)

    assert parsed is not None
    assert parsed.recent_requests.split(" · ") == [
        "Update the panel",
        "Update the panel with the standard spacing",
        "Recover the missing legacy request",
    ]


def test_malformed_new_fields_do_not_erase_handoff(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    later = (now + timedelta(minutes=1)).isoformat()
    path = _write_session(
        tmp_path,
        _message("user", "Ship the release"),
        _shell_input("git push", "shell"),
        {**_shell_result(["shell"], "OK"), "timestamp": later},
        _summary("The local release is ready.", timestamp=now.isoformat()),
        {"type": "attachment", "attachment": ["queued_command"], "timestamp": later},
        {**_queue({"text": "malformed prompt"}, humanTurn=True), "timestamp": later},
        _summary({"text": "malformed summary"}, timestamp=later),
        _message(
            "user", "Unexpected compact flag", isCompactSummary={"flag": True}, timestamp=later
        ),
    )

    prompt = _report(tmp_path)
    parsed = mod._parse_session(path)
    assert parsed is not None and parsed.last_active == now
    assert "Ship the release" in prompt
    assert "Summary at the end of the last session: The local release is ready." in prompt
    assert "Progress made: (none recorded)" in prompt
    assert "Unexpected compact flag" not in prompt
    assert "malformed prompt" not in prompt and "malformed summary" not in prompt


def test_main_handoff_for_release_with_height_followup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("USAGE_LANG", "zh-TW")
    height = "請把面板高度統一，保留足球面板的例外"
    summary = "v0.34.24 已發版並安裝。截圖已修好，這一輪已收尾。"
    _write_session(
        tmp_path,
        _shell_input("gh pr merge 385 --merge --delete-branch", "pr385"),
        _shell_result("pr385", "Fast-forward"),
        _shell_input('git tag -a v0.34.24 -m "v0.34.24" && git push origin v0.34.24', "tag"),
        _shell_result("tag", stderr=" * [new tag] v0.34.24 -&gt; v0.34.24"),
        _queue([{"type": "text", "text": height}], humanTurn=True),
        {"type": "system", "subtype": "cost"},
        _message("user", height + "，以預設面板為準"),
        _copy(height),
        _message("user", "全部處理好"),
        _shell_input("gh pr merge 386 --merge --delete-branch", "pr386"),
        _shell_result("pr386", "Fast-forward"),
        _message("assistant", "原始回覆。"),
        _summary(summary),
    )
    payload = {"source": "startup", "transcript_path": str(tmp_path / "new.jsonl")}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    assert mod.main() == 0
    output = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert output["hookEventName"] == "SessionStart"
    prompt = output["additionalContext"]
    assert "merged PR #386 · pushed · tagged v0.34.24 · merged PR #385" in prompt
    assert "上次結束時的摘要：" + summary in prompt
    assert "Claude 上次最後說：" not in prompt
    assert "gh pr merge" not in prompt and "git tag" not in prompt
    assert prompt.count(height) == 1
    assert height + "，以預設面板為準" in prompt


def test_hook_source_parses_with_python39_grammar() -> None:
    path = Path(mod.__file__)
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))
