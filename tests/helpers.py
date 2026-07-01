from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import setup_hook


def write_codex_session(
    path: Path,
    *,
    session_id: str,
    timestamp: str,
    usage: dict[str, Any] | None = None,
    rate_limits: dict[str, Any] | None = None,
    mtime: float | None = None,
    cwd: str = "/tmp/demo",
) -> None:
    lines = [
        {
            "type": "session_meta",
            "payload": {"id": session_id, "timestamp": timestamp, "cwd": cwd},
        },
        {
            "type": "event_msg",
            "timestamp": timestamp,
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": usage or {"input_tokens": 1}},
                "rate_limits": rate_limits,
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def write_codex_session_with_turn_context_model(
    path: Path,
    *,
    session_id: str,
    timestamp: str,
    model: str,
    usage: dict[str, Any],
    rate_limits: dict[str, Any] | None = None,
    mtime: float | None = None,
    cwd: str = "/tmp/demo",
) -> None:
    lines = [
        {
            "type": "session_meta",
            "payload": {"id": session_id, "timestamp": timestamp, "cwd": cwd},
        },
        {
            "type": "turn_context",
            "payload": {"model": model, "cwd": cwd},
        },
        {
            "type": "event_msg",
            "timestamp": timestamp,
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": usage},
                "rate_limits": rate_limits,
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


@dataclass(frozen=True)
class SetupHookPaths:
    settings: Path
    hook_target: Path
    forwarder_target: Path
    status_file: Path
    hook_source: Path
    forwarder_source: Path


def patch_setup_hook_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    hook_source_name: str = "hook_source.py",
    forwarder_source_name: str = "forwarder_source.py",
    hook_source_text: str = "print('hook')\n",
    forwarder_source_text: str = "print('forwarder')\n",
    legacy_name: str | None = None,
) -> SetupHookPaths:
    claude_dir = tmp_path / ".claude"
    settings = claude_dir / "settings.json"
    hook_target = claude_dir / "usage-statusline.py"
    forwarder_target = claude_dir / "usage-statusline-forwarder.py"
    status_file = claude_dir / "usage-status.json"
    hook_source = tmp_path / hook_source_name
    forwarder_source = tmp_path / forwarder_source_name
    hook_source.write_text(hook_source_text, encoding="utf-8")
    forwarder_source.write_text(forwarder_source_text, encoding="utf-8")
    claude_dir.mkdir()
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", settings)
    monkeypatch.setattr(setup_hook, "HOOK_TARGET", hook_target)
    monkeypatch.setattr(setup_hook, "FORWARDER_TARGET", forwarder_target)
    monkeypatch.setattr(setup_hook, "STATUS_FILE", status_file)
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", tmp_path / ".codex" / "config.toml")
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", tmp_path / ".codex" / "usage-backup.json")
    monkeypatch.setattr(setup_hook, "_resolve_hook_source", lambda: hook_source)
    monkeypatch.setattr(setup_hook, "_resolve_forwarder_source", lambda: forwarder_source)
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/python3")
    if legacy_name is not None:
        monkeypatch.setattr(
            setup_hook,
            "LEGACY_HOOK_TARGET",
            claude_dir / f"{legacy_name}-statusline.py",
        )
        monkeypatch.setattr(
            setup_hook,
            "LEGACY_STATUS_FILE",
            claude_dir / f"{legacy_name}-status.json",
        )
    return SetupHookPaths(
        settings=settings,
        hook_target=hook_target,
        forwarder_target=forwarder_target,
        status_file=status_file,
        hook_source=hook_source,
        forwarder_source=forwarder_source,
    )


@dataclass(frozen=True)
class ResumeHookPaths:
    settings: Path
    resume_target: Path
    sidecar: Path
    source: Path


def patch_resume_hook_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    source_name: str = "usage_session_resume.py",
    source_text: str = '__version__ = "1.0"\nprint("resume")\n',
) -> ResumeHookPaths:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    resume_target = claude_dir / "usage-session-resume.py"
    sidecar = claude_dir / "usage-resume-prompt.json"
    source = tmp_path / source_name
    source.write_text(source_text, encoding="utf-8")
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", settings)
    monkeypatch.setattr(setup_hook, "RESUME_HOOK_TARGET", resume_target)
    monkeypatch.setattr(setup_hook, "RESUME_PROMPT_SIDECAR", sidecar)
    monkeypatch.setattr(setup_hook, "_resolve_resume_source", lambda: source)
    return ResumeHookPaths(
        settings=settings,
        resume_target=resume_target,
        sidecar=sidecar,
        source=source,
    )
