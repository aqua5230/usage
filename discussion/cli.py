# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Headless CLI detection, event parsing, and process streaming."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

from discussion.usage import TurnUsage

DetectionSource = Literal["which", "candidate_dir", "user_configured", "not_found"]

# Every built-in CLI defaults to a dedicated neutral cwd to block project-level
# instructions and repository agent rules from contaminating council answers.
# Claude's --bare mode is intentionally not used: it also disables OAuth/keychain
# authentication, which would break subscription-based users.
# Isolation differs by CLI: Claude combines --safe-mode with --setting-sources
# project for full customization isolation. Codex and Antigravity cannot isolate
# user-level instructions with flags, so prompts can only mitigate their influence.
CANDIDATE_DIRECTORIES = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path("~/.local/bin"),
)
NEUTRAL_DISCUSSION_CWD = Path("~/.usage/discussion-cwd")
NEUTRAL_CONFIG_NAMES = frozenset(
    {
        ".agents",
        ".claude",
        ".codex",
        ".gemini",
        ".mcp.json",
        "agents.md",
        "claude.md",
        "gemini.md",
        "settings.json",
        "settings.local.json",
    }
)
DEFAULT_TIMEOUT_SECONDS = 120.0
TERMINATION_GRACE_SECONDS = 2.0
STDERR_TAIL_LINES = 50
MAX_STREAM_OUTPUT_CHARS = 40_000
TRUNCATION_MARKER = "\n[內容已截斷]"
POLL_INTERVAL_SECONDS = 0.02
# Short values are too likely to occur in ordinary output and cause false redactions.
MIN_REDACTED_ENV_VALUE_LENGTH = 8

ANSI_ESCAPE_RE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SENSITIVE_ENV_NAME_RE = re.compile(
    # PAT excludes PATH: redacting the PATH value would gut every error message.
    r"(?:TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE|PRIVATE|PAT(?!H))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DetectionResult:
    adapter_id: str
    available: bool
    path: str | None
    source: DetectionSource
    error: str | None = None


@dataclass(frozen=True)
class Invocation:
    argv: tuple[str, ...]
    cwd: str | None
    env_overrides: Mapping[str, str]
    timeout_seconds: float


class CLIAdapter(Protocol):
    adapter_id: str
    supports_token_stream: bool

    def detect(self) -> DetectionResult: ...

    def build_invocation(self, prompt: str, model: str | None) -> Invocation: ...

    def parse_stdout_line(self, line: str) -> tuple[str | None, bool]: ...

    def take_final_text(self) -> str | None: ...

    def take_usage(self) -> TurnUsage | None: ...


class CLIUnavailableError(RuntimeError):
    """Raised when an invocation is requested for an unavailable adapter."""


class StreamFailureReason:
    """Machine-readable reasons for a failed CLI stream."""

    LAUNCH = "launch"
    TIMEOUT = "timeout"
    NONZERO_EXIT = "nonzero_exit"
    READER = "reader"
    INCOMPLETE = "incomplete"


class StreamError(str):
    """A stream failure message that retains its reason for the caller."""

    reason: str

    def __new__(cls, message: str, reason: str) -> StreamError:
        instance = super().__new__(cls, message)
        instance.reason = reason
        return instance


class NeutralWorkingDirectoryError(RuntimeError):
    """Raised when the isolated CLI working directory cannot be used safely."""


class _JSONAdapter:
    adapter_id = ""
    executable_name = ""
    supports_token_stream = False

    def __init__(
        self,
        user_configured_path: str | None = None,
        *,
        cwd: str | None = None,
        read_only: bool = False,
        env_overrides: Mapping[str, str] | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        extra_read_dirs: Sequence[str] | None = None,
    ) -> None:
        self._user_configured_path = user_configured_path
        self._cwd = cwd
        self._read_only = read_only
        self._env_overrides = dict(env_overrides or {})
        self._timeout_seconds = timeout_seconds
        # Directories the CLI is allowed to read in addition to its working
        # directory (used to grant access to attachment folders). Stored as an
        # immutable tuple; non-existent entries are filtered out at invocation
        # time so a missing folder never makes the CLI error out.
        self._extra_read_dirs = tuple(extra_read_dirs or ())
        self._parse_error_count = 0
        self._parse_error_lock = threading.Lock()
        self._usage: TurnUsage | None = None

    @property
    def parse_error_count(self) -> int:
        with self._parse_error_lock:
            return self._parse_error_count

    def detect(self) -> DetectionResult:
        configured = self._user_configured_path
        if configured is not None:
            configured_path = Path(configured)
            if not configured_path.is_absolute():
                return DetectionResult(
                    self.adapter_id,
                    False,
                    None,
                    "user_configured",
                    "configured CLI path must be absolute",
                )
            if _is_executable(configured_path):
                return DetectionResult(
                    self.adapter_id,
                    True,
                    str(configured_path),
                    "user_configured",
                )
            return DetectionResult(
                self.adapter_id,
                False,
                str(configured_path),
                "user_configured",
                "configured CLI path is missing or not executable",
            )

        found = shutil.which(self.executable_name)
        if found is not None:
            return DetectionResult(self.adapter_id, True, found, "which")

        for directory in CANDIDATE_DIRECTORIES:
            candidate = directory.expanduser() / self.executable_name
            if _is_executable(candidate):
                return DetectionResult(
                    self.adapter_id,
                    True,
                    str(candidate),
                    "candidate_dir",
                )
        return DetectionResult(self.adapter_id, False, None, "not_found")

    def _require_path(self) -> str:
        detection = self.detect()
        if not detection.available or detection.path is None:
            detail = f": {detection.error}" if detection.error else ""
            raise CLIUnavailableError(f"{self.adapter_id} CLI is unavailable{detail}")
        return detection.path

    def _invocation(self, argv: Sequence[str]) -> Invocation:
        if self._read_only:
            if self._cwd is None:
                raise ValueError("read-only project mode requires a working directory")
            cwd = validate_project_working_directory(self._cwd)
        else:
            cwd = self._cwd or resolve_neutral_working_directory()
        return Invocation(
            argv=tuple(argv),
            cwd=cwd,
            env_overrides=dict(self._env_overrides),
            timeout_seconds=self._timeout_seconds,
        )

    def _load_event(self, line: str) -> dict[str, object] | None:
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            self._record_parse_error()
            return None
        if not isinstance(value, dict):
            self._record_parse_error()
            return None
        return cast(dict[str, object], value)

    def _record_parse_error(self) -> None:
        with self._parse_error_lock:
            self._parse_error_count += 1

    def _resolved_read_dirs(self) -> tuple[str, ...]:
        resolved: list[str] = []
        for raw in self._extra_read_dirs:
            path = Path(raw).expanduser()
            if path.is_dir():
                resolved.append(str(path.resolve()))
        return tuple(resolved)

    def take_final_text(self) -> str | None:
        return None

    def take_usage(self) -> TurnUsage | None:
        usage = self._usage
        self._usage = None
        return usage


class ClaudeAdapter(_JSONAdapter):
    adapter_id = "claude"
    executable_name = "claude"
    supports_token_stream = True

    def build_invocation(self, prompt: str, model: str | None) -> Invocation:
        self._usage = None
        argv = [self._require_path(), "-p"]
        if self._read_only:
            # `--tools` is variadic (`<tools...>`): it keeps consuming argv
            # tokens until the next flag. It must not directly precede the
            # trailing prompt, or claude swallows the prompt as a tool name and
            # dies with "Input must be provided ... when using --print". Keep a
            # non-variadic flag (`--safe-mode`) right after it.
            argv.extend(("--tools", "Read,Grep,Glob"))
        else:
            # Without an attached project, participants have nothing to read
            # and the council prompt already prohibits tool calls. Disable the
            # built-in toolset rather than paying for its schema on every turn.
            # `--safe-mode` below also prevents this variadic flag from
            # consuming the trailing prompt.
            argv.extend(("--tools", ""))
        # `--add-dir` is variadic (`<directories...>`), the same trap as
        # `--tools` above: it must not sit right before the trailing prompt.
        # Emit one `--add-dir <dir>` per folder, then let the non-variadic
        # `--safe-mode` that follows act as the stopper so the prompt survives.
        for directory in self._resolved_read_dirs():
            argv.extend(("--add-dir", directory))
        argv.extend(
            (
                "--safe-mode",
                "--exclude-dynamic-system-prompt-sections",
                "--setting-sources",
                "project",
                "--output-format",
                "stream-json",
                "--include-partial-messages",
                "--verbose",
            )
        )
        if model is not None:
            argv.extend(("--model", model))
        argv.append(prompt)
        return self._invocation(argv)

    def parse_stdout_line(self, line: str) -> tuple[str | None, bool]:
        event = self._load_event(line)
        if event is None:
            return None, False
        event_type = event.get("type")
        if event_type == "result":
            self._usage = _claude_usage(event.get("usage"))
            return None, True
        if event_type != "stream_event":
            return None, False
        stream_event = event.get("event")
        if not isinstance(stream_event, dict):
            self._record_parse_error()
            return None, False
        if stream_event.get("type") == "message_stop":
            return None, True
        if stream_event.get("type") != "content_block_delta":
            return None, False
        delta = stream_event.get("delta")
        if not isinstance(delta, dict) or delta.get("type") != "text_delta":
            return None, False
        text = delta.get("text")
        if not isinstance(text, str):
            self._record_parse_error()
            return None, False
        return text, False


class CodexAdapter(_JSONAdapter):
    adapter_id = "codex"
    executable_name = "codex"
    supports_token_stream = False

    def build_invocation(self, prompt: str, model: str | None) -> Invocation:
        self._usage = None
        argv = [
            self._require_path(),
            "exec",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--json",
        ]
        if self._read_only:
            argv.extend(("-s", "read-only"))
        # `--add-dir` takes a single `<DIR>`; repeat once per folder. Placed
        # alongside the other flags so the prompt stays the trailing argument.
        for directory in self._resolved_read_dirs():
            argv.extend(("--add-dir", directory))
        if model is not None:
            argv.extend(("--model", model))
        argv.append(prompt)
        return self._invocation(argv)

    def parse_stdout_line(self, line: str) -> tuple[str | None, bool]:
        event = self._load_event(line)
        if event is None:
            return None, False
        event_type = event.get("type")
        if event_type == "turn.completed":
            self._usage = _codex_usage(event.get("usage"))
            return None, True
        if event_type != "item.completed":
            return None, False
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            return None, False
        text = item.get("text")
        if not isinstance(text, str):
            self._record_parse_error()
            return None, False
        return text, False


class AgyAdapter(_JSONAdapter):
    adapter_id = "agy"
    executable_name = "agy"
    supports_token_stream = True
    _final_text: str | None = None

    def build_invocation(self, prompt: str, model: str | None) -> Invocation:
        self._final_text = None
        self._usage = None
        # agy has no equivalent of Claude's or Codex's user-config isolation flag.
        # The neutral cwd blocks project-level AGENTS.md only; user settings may apply.
        # Project mode can only change cwd; agy exposes no read-only sandbox flag.
        argv = [self._require_path(), "--output-format", "stream-json"]
        if model is not None:
            argv.extend(("--model", model))
        # `--add-dir` is repeatable; emit one per folder before `-p <prompt>`
        # so the prompt remains the final argument.
        for directory in self._resolved_read_dirs():
            argv.extend(("--add-dir", directory))
        argv.extend(("-p", prompt))
        return self._invocation(argv)

    def parse_stdout_line(self, line: str) -> tuple[str | None, bool]:
        event = self._load_event(line)
        if event is None:
            return None, False
        event_type = event.get("event")
        if event_type == "result":
            result = event.get("result")
            if isinstance(result, dict):
                response = result.get("response")
                if isinstance(response, str) and response:
                    self._final_text = response
                self._usage = _agy_usage(result.get("usage"))
            return None, True
        if event_type != "step_update":
            return None, False
        step_update = event.get("step_update")
        if not isinstance(step_update, dict):
            self._record_parse_error()
            return None, False
        if step_update.get("step_type") != "agent_response":
            return None, False
        text = step_update.get("text_delta")
        if not isinstance(text, str):
            self._record_parse_error()
            return None, False
        return text, False

    def take_final_text(self) -> str | None:
        final_text = self._final_text
        self._final_text = None
        return final_text


def build_argv_invocation(
    executable: str,
    args_before_prompt: Sequence[str],
    args_after_prompt: Sequence[str],
    prompt: str,
    *,
    cwd: str | None = None,
    env_overrides: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Invocation:
    return Invocation(
        argv=(executable, *args_before_prompt, prompt, *args_after_prompt),
        cwd=cwd,
        env_overrides=dict(env_overrides or {}),
        timeout_seconds=timeout_seconds,
    )


def build_login_shell_invocation(
    script: str,
    prompt: str,
    *,
    opt_in: bool,
    cwd: str | None = None,
    env_overrides: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Invocation:
    if not opt_in:
        raise ValueError("login-shell mode requires explicit opt-in")
    return Invocation(
        argv=("/bin/zsh", "-lic", script, "usage-discussion", prompt),
        cwd=cwd,
        env_overrides=dict(env_overrides or {}),
        timeout_seconds=timeout_seconds,
    )


class _Completion:
    def __init__(
        self,
        on_done: Callable[[], None],
        on_error: Callable[[str], None],
        on_cancelled: Callable[[], None],
    ) -> None:
        self._on_done = on_done
        self._on_error = on_error
        self._on_cancelled = on_cancelled
        self._committed = False
        self._lock = threading.Lock()

    def done(self) -> bool:
        with self._lock:
            if self._committed:
                return False
            self._committed = True
        self._on_done()
        return True

    def error(self, message: str) -> bool:
        with self._lock:
            if self._committed:
                return False
            self._committed = True
        self._on_error(message)
        return True

    def cancelled(self) -> bool:
        with self._lock:
            if self._committed:
                return False
            self._committed = True
        self._on_cancelled()
        return True


def run_streaming(
    adapter: CLIAdapter,
    invocation: Invocation,
    on_delta: Callable[[str], None],
    on_done: Callable[[], None],
    on_error: Callable[[str], None],
    on_cancelled: Callable[[], None],
    on_final_text: Callable[[str], None] | None = None,
    on_usage: Callable[[TurnUsage], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    cancel_event = cancel_event or threading.Event()
    completion = _Completion(on_done, on_error, on_cancelled)
    merged_env = os.environ.copy()
    merged_env.update(invocation.env_overrides)
    try:
        process = subprocess.Popen(
            invocation.argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=True,
            cwd=invocation.cwd,
            env=merged_env,
        )
    except OSError as exc:
        completion.error(
            StreamError(
                _redact_environment_values(str(exc), merged_env),
                StreamFailureReason.LAUNCH,
            )
        )
        return

    assert process.stdout is not None
    assert process.stderr is not None
    stderr_tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
    stdout_tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
    reader_errors: list[str] = []
    reader_error_lock = threading.Lock()
    parser_reported_done = threading.Event()
    output_state = _OutputState()

    def read_stdout() -> None:
        try:
            for raw_line in cast(Iterator[str], process.stdout):
                line = _clean_text(raw_line)
                stdout_tail.append(line.rstrip("\n"))
                delta, is_done = adapter.parse_stdout_line(line)
                if delta is not None:
                    bounded = output_state.apply(_clean_text(delta))
                    if bounded:
                        on_delta(bounded)
                if is_done:
                    parser_reported_done.set()
        except (OSError, ValueError) as exc:
            with reader_error_lock:
                reader_errors.append(f"stdout read failed: {exc}")

    def read_stderr() -> None:
        try:
            for raw_line in cast(Iterator[str], process.stderr):
                stderr_tail.append(_clean_text(raw_line).rstrip("\n"))
        except (OSError, ValueError) as exc:
            with reader_error_lock:
                reader_errors.append(f"stderr read failed: {exc}")

    stdout_thread = threading.Thread(target=read_stdout, name="discussion-cli-stdout")
    stderr_thread = threading.Thread(target=read_stderr, name="discussion-cli-stderr")
    stdout_thread.start()
    stderr_thread.start()

    deadline = time.monotonic() + max(0.0, invocation.timeout_seconds)
    termination_reason: Literal["cancelled", "timeout"] | None = None
    while True:
        returncode = process.poll()
        if returncode is not None:
            break
        if cancel_event.is_set():
            termination_reason = "cancelled"
            _terminate_process_group(process)
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            termination_reason = "timeout"
            _terminate_process_group(process)
            break
        cancel_event.wait(min(POLL_INTERVAL_SECONDS, remaining))

    stdout_thread.join(timeout=TERMINATION_GRACE_SECONDS)
    stderr_thread.join(timeout=TERMINATION_GRACE_SECONDS)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        with reader_error_lock:
            reader_errors.append("stream reader did not stop")

    if termination_reason == "cancelled":
        completion.cancelled()
        return
    if termination_reason == "timeout":
        completion.error(
            StreamError(
                f"CLI invocation timed out after {invocation.timeout_seconds:g} seconds",
                StreamFailureReason.TIMEOUT,
            )
        )
        return
    if reader_errors:
        message = "\n".join(reader_errors)
        completion.error(
            StreamError(
                _redact_environment_values(message, merged_env),
                StreamFailureReason.READER,
            )
        )
        return

    returncode = process.returncode
    if returncode is None:
        returncode = process.wait()
    if returncode != 0:
        stderr_message = "\n".join(stderr_tail).strip()
        stdout_message = "\n".join(stdout_tail).strip()
        message = stderr_message or stdout_message or f"CLI exited with status {returncode}"
        completion.error(
            StreamError(
                _redact_environment_values(message, merged_env),
                StreamFailureReason.NONZERO_EXIT,
            )
        )
        return

    if not parser_reported_done.is_set():
        completion.error(
            StreamError(
                "CLI exited without a completion event; output may be incomplete",
                StreamFailureReason.INCOMPLETE,
            )
        )
        return
    final_text = adapter.take_final_text()
    if final_text and on_final_text is not None:
        on_final_text(output_state.replace(_clean_text(final_text)))
    usage = adapter.take_usage()
    if usage is not None and on_usage is not None:
        on_usage(usage)
    completion.done()


def _usage_value(usage: object, key: str) -> int:
    if not isinstance(usage, dict):
        return 0
    value = usage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _claude_usage(usage: object) -> TurnUsage:
    input_tokens = _usage_value(usage, "input_tokens")
    output_tokens = _usage_value(usage, "output_tokens")
    total_tokens = (
        input_tokens
        + _usage_value(usage, "cache_creation_input_tokens")
        + _usage_value(usage, "cache_read_input_tokens")
        + output_tokens
    )
    return TurnUsage(input_tokens, output_tokens, total_tokens)


def _codex_usage(usage: object) -> TurnUsage:
    input_tokens = _usage_value(usage, "input_tokens")
    output_tokens = _usage_value(usage, "output_tokens") + _usage_value(
        usage, "reasoning_output_tokens"
    )
    total_tokens = (
        input_tokens
        + _usage_value(usage, "cached_input_tokens")
        + _usage_value(usage, "cache_write_input_tokens")
        + output_tokens
    )
    return TurnUsage(input_tokens, output_tokens, total_tokens)


def _agy_usage(usage: object) -> TurnUsage:
    return TurnUsage(
        _usage_value(usage, "input_tokens"),
        _usage_value(usage, "output_tokens"),
        _usage_value(usage, "total_tokens"),
    )


class _OutputState:
    def __init__(self) -> None:
        self._length = 0
        self._truncated = False
        self._lock = threading.Lock()

    def apply(self, delta: str) -> str:
        with self._lock:
            if self._truncated:
                return ""
            remaining = MAX_STREAM_OUTPUT_CHARS - self._length
            if len(delta) <= remaining:
                self._length += len(delta)
                return delta
            self._truncated = True
            prefix = delta[: max(0, remaining)]
            self._length += len(prefix)
            return prefix + TRUNCATION_MARKER

    def replace(self, text: str) -> str:
        with self._lock:
            self._length = 0
            self._truncated = False
        return self.apply(text)


def _is_executable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def validate_project_working_directory(path: str) -> str:
    if not path.strip():
        raise ValueError("working directory must not be blank")
    project_path = Path(path).expanduser()
    try:
        if not project_path.exists():
            raise ValueError(f"working directory does not exist: {project_path}")
        if not project_path.is_dir():
            raise ValueError(f"working directory is not a directory: {project_path}")
        return str(project_path.resolve())
    except OSError as exc:
        raise ValueError(f"cannot access working directory {project_path}: {exc}") from exc


def resolve_neutral_working_directory(path: Path | None = None) -> str:
    neutral_path = (path or NEUTRAL_DISCUSSION_CWD).expanduser()
    try:
        if neutral_path.is_symlink():
            raise NeutralWorkingDirectoryError(
                f"neutral working directory must not be a symlink: {neutral_path}"
            )
        neutral_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not neutral_path.is_dir():
            raise NeutralWorkingDirectoryError(
                f"neutral working directory is not a directory: {neutral_path}"
            )
        conflicts = sorted(
            entry.name
            for entry in neutral_path.iterdir()
            if entry.name.lower() in NEUTRAL_CONFIG_NAMES
        )
    except NeutralWorkingDirectoryError:
        raise
    except OSError as exc:
        raise NeutralWorkingDirectoryError(
            f"cannot prepare neutral working directory {neutral_path}: {exc}"
        ) from exc
    if conflicts:
        names = ", ".join(conflicts)
        raise NeutralWorkingDirectoryError(
            f"neutral working directory contains configuration files: {names}"
        )
    return str(neutral_path)


def _terminate_process_group_posix(process: subprocess.Popen[str]) -> None:
    try:
        process_group = os.getpgid(process.pid)  # type: ignore[attr-defined]
    except ProcessLookupError:
        return
    try:
        os.killpg(process_group, signal.SIGTERM)  # type: ignore[attr-defined]
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process_group, signal.SIGKILL)  # type: ignore[attr-defined]
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        return


def _terminate_process_group_win(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    process.kill()
    try:
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        return


# AI Council only runs its GUI on macOS today (see discussion_window.py), but
# this CLI layer is imported and type-checked on Windows CI too. `start_new_session`
# on the Popen call above is a POSIX-only no-op on Windows, so termination there
# falls back to plain terminate()/kill() instead of process-group signals.
_terminate_process_group = (
    _terminate_process_group_win if sys.platform == "win32" else _terminate_process_group_posix
)


def _clean_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return CONTROL_RE.sub("", ANSI_ESCAPE_RE.sub("", normalized))


def _redact_environment_values(message: str, environment: Mapping[str, str]) -> str:
    redacted = message
    for name, value in environment.items():
        if len(value) >= MIN_REDACTED_ENV_VALUE_LENGTH and SENSITIVE_ENV_NAME_RE.search(name):
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted
