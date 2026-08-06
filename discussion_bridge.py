# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""PyObjC-free orchestration for one AI council discussion at a time."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from discussion_cli import (
    DEFAULT_TIMEOUT_SECONDS,
    AgyAdapter,
    ClaudeAdapter,
    CLIAdapter,
    CodexAdapter,
    DetectionResult,
    Invocation,
    StreamError,
    StreamFailureReason,
    build_argv_invocation,
    build_login_shell_invocation,
    resolve_neutral_working_directory,
    run_streaming,
    validate_project_working_directory,
)
from discussion_session import (
    ConsensusCount,
    DebateStyle,
    DiscussionEvent,
    DiscussionSession,
    Participant,
    SessionStatus,
    build_moderator_prompt,
    build_round1_prompt,
    build_round2_prompt,
    truncate_guidance,
)
from discussion_usage import TurnUsage
from i18n import _t
from usage_lang import detect_lang

logger = logging.getLogger(__name__)

MAX_CONCURRENT_PROCESSES = 4
DELTA_FLUSH_CHARS = 128
DELTA_FLUSH_SECONDS = 0.05
GUIDANCE_TIMEOUT_SECONDS = 300.0
DISCUSSIONS_DIRECTORY = Path("~/.usage/discussions").expanduser()

ParticipantSource = Literal["builtin", "argv", "login_shell"]
AdapterFactory = Callable[["ParticipantSpec"], CLIAdapter]


class DiscussionBusyError(RuntimeError):
    """Raised when start is called while the current session is still running."""


@dataclass(frozen=True)
class ParticipantSpec:
    id: str
    label: str
    adapter_id: str
    model: str | None = None
    source: ParticipantSource = "builtin"
    executable: str | None = None
    args_before_prompt: tuple[str, ...] = ()
    args_after_prompt: tuple[str, ...] = ()
    login_shell_script: str | None = None
    login_shell_opt_in: bool = False
    cwd: str | None = None
    read_only: bool = False
    extra_read_dirs: tuple[str, ...] = ()
    env_overrides: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    supports_token_stream: bool = False
    persona_prompt: str | None = None
    persona_label: str | None = None


@dataclass(frozen=True)
class _ResolvedParticipant:
    spec: ParticipantSpec
    adapter: CLIAdapter | None
    detection: DetectionResult


@dataclass(frozen=True)
class _TurnResult:
    participant: _ResolvedParticipant
    turn_id: str | None
    success: bool
    text: str
    error: str | None


class _DeltaAccumulator:
    def __init__(self) -> None:
        self._parts: list[str] = []
        self._length = 0
        self._last_flush = time.monotonic()
        self._lock = threading.Lock()

    def add(self, text: str) -> str:
        with self._lock:
            self._parts.append(text)
            self._length += len(text)
            now = time.monotonic()
            if (
                self._length < DELTA_FLUSH_CHARS
                and now - self._last_flush < DELTA_FLUSH_SECONDS
            ):
                return ""
            return self._take_locked(now)

    def flush(self) -> str:
        with self._lock:
            return self._take_locked(time.monotonic())

    def _take_locked(self, now: float) -> str:
        if not self._parts:
            return ""
        value = "".join(self._parts)
        self._parts.clear()
        self._length = 0
        self._last_flush = now
        return value


class _CustomLineAdapter:
    def __init__(self, spec: ParticipantSpec) -> None:
        self.adapter_id = spec.adapter_id
        self.supports_token_stream = spec.supports_token_stream
        self._spec = spec

    def detect(self) -> DetectionResult:
        if self._spec.source == "login_shell":
            shell = Path("/bin/zsh")
            available = shell.is_file() and os.access(shell, os.X_OK)
            return DetectionResult(
                self.adapter_id,
                available,
                str(shell) if available else None,
                "user_configured" if available else "not_found",
                None if available else "/bin/zsh is missing or not executable",
            )
        executable = self._spec.executable
        if not executable:
            return DetectionResult(
                self.adapter_id,
                False,
                None,
                "not_found",
                "custom executable is required",
            )
        path = Path(executable)
        if path.is_absolute():
            available = path.is_file() and os.access(path, os.X_OK)
            return DetectionResult(
                self.adapter_id,
                available,
                str(path),
                "user_configured",
                None if available else "custom executable is missing or not executable",
            )
        found = shutil.which(executable)
        return DetectionResult(
            self.adapter_id,
            found is not None,
            found,
            "which" if found is not None else "not_found",
            None if found is not None else f"custom executable not found: {executable}",
        )

    def build_invocation(self, prompt: str, model: str | None) -> Invocation:
        if self._spec.read_only:
            raise ValueError("read-only project mode is unavailable for custom participants")
        cwd = self._spec.cwd or resolve_neutral_working_directory()
        if self._spec.source == "login_shell":
            script = self._spec.login_shell_script
            if script is None:
                raise ValueError("login-shell command requires login_shell_script")
            return build_login_shell_invocation(
                script,
                prompt,
                opt_in=self._spec.login_shell_opt_in,
                cwd=cwd,
                env_overrides=self._spec.env_overrides,
                timeout_seconds=self._spec.timeout_seconds,
            )
        detection = self.detect()
        if not detection.available or detection.path is None:
            raise ValueError(detection.error or "custom executable is unavailable")
        return build_argv_invocation(
            detection.path,
            self._spec.args_before_prompt,
            self._spec.args_after_prompt,
            prompt,
            cwd=cwd,
            env_overrides=self._spec.env_overrides,
            timeout_seconds=self._spec.timeout_seconds,
        )

    def parse_stdout_line(self, line: str) -> tuple[str | None, bool]:
        return (line, False) if line else (None, False)

    def take_final_text(self) -> str | None:
        return None

    def take_usage(self) -> TurnUsage | None:
        return None


class DiscussionBridge:
    def __init__(self, adapter_factory: AdapterFactory | None = None) -> None:
        self._adapter_factory = adapter_factory or _default_adapter_factory
        self._session: DiscussionSession | None = None
        self._worker: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._guidance_event = threading.Event()
        self._guidance_lock = threading.Lock()
        self._guidance_text: str | None = None
        self._state_lock = threading.Lock()
        self._event_order_lock = threading.RLock()
        self._event_lock = threading.Lock()
        self._events: deque[DiscussionEvent] = deque()
        self._event_listener: Callable[[], None] | None = None
        self._callbacks_enabled = True
        self._working_directory: str | None = None

    def detect_participants(self) -> list[DetectionResult]:
        return [
            ClaudeAdapter().detect(),
            CodexAdapter().detect(),
            AgyAdapter().detect(),
        ]

    def start(
        self,
        topic: str,
        participants: Sequence[ParticipantSpec],
        moderator_id: str | None = None,
        working_directory: str | None = None,
        attachments: Sequence[str] | None = None,
        total_rounds: int = 2,
        include_summary: bool = True,
        end_on_consensus: bool = False,
        guidance_between_rounds: bool = False,
        debate_style: DebateStyle = DebateStyle.CONSTRUCTIVE,
    ) -> str:
        normalized_topic = topic.strip()
        if not normalized_topic:
            raise ValueError("topic must not be blank")
        specs = tuple(participants)
        if not specs:
            raise ValueError("at least one participant is required")
        project_cwd = (
            validate_project_working_directory(working_directory)
            if working_directory is not None
            else None
        )
        if project_cwd is not None:
            specs = tuple(
                replace(spec, cwd=project_cwd, read_only=True) for spec in specs
            )
        # Grant each CLI read access to the folders holding the attached
        # images, so non-interactive mode can open files outside the working
        # directory without an approval prompt. Only the attachment folders
        # themselves — never the home directory or wider paths.
        attachment_dirs = _attachment_dirs(attachments or ())
        if attachment_dirs:
            specs = tuple(
                replace(spec, extra_read_dirs=attachment_dirs) for spec in specs
            )
        participant_models = [
            Participant(
                id=spec.id,
                label=spec.label,
                adapter_id=spec.adapter_id,
                model=spec.model,
                is_moderator=spec.id == moderator_id,
                persona_label=spec.persona_label,
            )
            for spec in specs
        ]
        rounds = min(5, max(1, total_rounds))
        session = DiscussionSession(
            normalized_topic, participant_models, total_rounds=rounds
        )
        # The session keeps the user's original topic for display; only the
        # prompt handed to each CLI carries the appended image paths.
        effective_topic = normalized_topic + build_attachment_block(
            attachments or (), detect_lang()
        )
        cancel_event = threading.Event()
        with self._guidance_lock:
            self._guidance_text = None
            self._guidance_event.clear()
        with self._state_lock:
            if self._worker is not None and self._worker.is_alive():
                raise DiscussionBusyError("a discussion session is already running")
            self._session = session
            self._working_directory = project_cwd
            self._cancel_event = cancel_event
            self._callbacks_enabled = True
            with self._event_lock:
                self._events.clear()
            session.transition(SessionStatus.PREPARING)
            worker = threading.Thread(
                target=self._run_session,
                args=(
                    session,
                    specs,
                    moderator_id,
                    effective_topic,
                    rounds,
                    include_summary,
                    end_on_consensus,
                    guidance_between_rounds,
                    debate_style,
                    cancel_event,
                ),
                name=f"discussion-session-{session.session_id}",
                daemon=True,
            )
            self._worker = worker
            worker.start()
        return session.session_id

    def stop(self) -> None:
        with self._state_lock:
            session = self._session
            cancel_event = self._cancel_event
        if session is None or cancel_event is None:
            return
        with self._event_order_lock:
            if session.status not in {
                SessionStatus.PREPARING,
                SessionStatus.ROUND1_RUNNING,
                SessionStatus.AWAITING_GUIDANCE,
                SessionStatus.ROUND2_RUNNING,
                SessionStatus.SUMMARIZING,
            }:
                return
            cancel_event.set()
            self._guidance_event.set()
            session.transition(SessionStatus.CANCELLING)
            for cancelled in session.cancel_incomplete_turns():
                self._enqueue_event_locked(cancelled)
            event = session.transition(SessionStatus.CANCELLED)
            if event is not None:
                self._enqueue_event_locked(event)

    def clear(self) -> dict[str, str]:
        """Drop the finished discussion so a new round can start fresh.

        Refuses while the worker thread is still alive (the UI must stop
        first); returns ``{"status": "busy"}`` rather than raising so a stray
        call never crashes the window. On success returns ``{"status": "ok"}``
        and ``snapshot()`` is empty afterwards. Never touches attachment files.
        """
        with self._state_lock:
            if self._worker is not None and self._worker.is_alive():
                return {"status": "busy"}
            self._session = None
            self._worker = None
            self._cancel_event = None
            self._working_directory = None
            with self._guidance_lock:
                self._guidance_text = None
                self._guidance_event.clear()
            with self._event_lock:
                self._events.clear()
        return {"status": "ok"}

    def submit_guidance(self, text: str) -> None:
        with self._guidance_lock:
            session = self._session
            if session is None or session.status is not SessionStatus.AWAITING_GUIDANCE:
                return
            self._guidance_text = truncate_guidance(text)
            self._guidance_event.set()

    def snapshot(self) -> dict[str, object]:
        with self._state_lock:
            session = self._session
            working_directory = self._working_directory
        if session is None:
            return {}
        snapshot = session.snapshot()
        snapshot["working_directory"] = working_directory
        return snapshot

    def drain_events(self, max_count: int = 50) -> list[dict[str, object]]:
        if max_count <= 0:
            return []
        drained: list[dict[str, object]] = []
        with self._event_lock:
            for _ in range(min(max_count, len(self._events))):
                drained.append(asdict(self._events.popleft()))
        return drained

    def set_event_listener(self, callback: Callable[[], None] | None) -> None:
        with self._event_lock:
            self._event_listener = callback

    def shutdown(self, timeout_seconds: float = 5.0) -> None:
        self.stop()
        with self._state_lock:
            worker = self._worker
        if worker is not None:
            worker.join(timeout=max(0.0, timeout_seconds))
        with self._event_order_lock, self._event_lock:
            self._callbacks_enabled = False
            self._event_listener = None

    def _run_session(
        self,
        session: DiscussionSession,
        specs: tuple[ParticipantSpec, ...],
        moderator_id: str | None,
        effective_topic: str,
        total_rounds: int,
        include_summary: bool,
        end_on_consensus: bool,
        guidance_between_rounds: bool,
        debate_style: DebateStyle,
        cancel_event: threading.Event,
    ) -> None:
        try:
            anonymous_labels = {
                participant.id: _anonymous_participant_label(index)
                for index, participant in enumerate(session.participants)
            }
            resolved = self._resolve_participants(specs)
            if cancel_event.is_set():
                return
            self._transition(session, cancel_event, SessionStatus.ROUND1_RUNNING)
            round1 = self._run_round(
                session,
                resolved,
                1,
                lambda participant: build_round1_prompt(
                    effective_topic,
                    persona=participant.spec.persona_prompt,
                ),
                cancel_event,
            )
            if cancel_event.is_set():
                return
            round1_survivors = [result for result in round1 if result.success]
            if not round1_survivors:
                self._transition(
                    session,
                    cancel_event,
                    SessionStatus.FAILED,
                    error="all participants failed in round 1",
                )
                return
            if len(round1_survivors) < 2:
                self._transition(session, cancel_event, SessionStatus.COMPLETED)
                return
            survivors = round1_survivors
            for round_index in range(2, total_rounds + 1):
                if len(survivors) < 2:
                    break
                guidance: str | None = None
                if guidance_between_rounds:
                    guidance = self._await_guidance(
                        session,
                        round_index,
                        cancel_event,
                    )
                    if cancel_event.is_set():
                        return
                else:
                    self._transition(
                        session,
                        cancel_event,
                        SessionStatus.ROUND2_RUNNING,
                        round_index=round_index,
                    )
                answers = [
                    (
                        anonymous_labels[result.participant.spec.id],
                        result.text,
                    )
                    for result in survivors
                ]

                def round_prompt(
                    participant: _ResolvedParticipant,
                    answers: list[tuple[str, str]] = answers,
                    prior_round: int = round_index - 1,
                    guidance: str | None = guidance,
                ) -> str:
                    return build_round2_prompt(
                        effective_topic,
                        answers,
                        prior_round=prior_round,
                        persona=participant.spec.persona_prompt,
                        style=debate_style,
                        guidance=guidance,
                    )

                round_results = self._run_round(
                    session,
                    [result.participant for result in survivors],
                    round_index,
                    round_prompt,
                    cancel_event,
                )
                consensus = self._publish_consensus_count(session, cancel_event)
                survivors = [
                    result
                    for result in round_results
                    if result.success
                ]
                if end_on_consensus and _is_unanimous_consensus(
                    consensus, len(round_results)
                ):
                    self._mark_consensus_reached(
                        session,
                        round_index,
                        cancel_event,
                    )
                    break
                if cancel_event.is_set() or not survivors:
                    break
            if cancel_event.is_set() or not survivors or not include_summary:
                self._transition(session, cancel_event, SessionStatus.COMPLETED)
                return

            moderator = _select_moderator(survivors, moderator_id)
            if moderator is None:
                self._transition(session, cancel_event, SessionStatus.COMPLETED)
                return
            self._transition(session, cancel_event, SessionStatus.SUMMARIZING)
            transcript = _build_transcript(session, anonymous_labels)
            self._run_turn(
                session,
                moderator.participant,
                total_rounds + 1,
                build_moderator_prompt(transcript),
                cancel_event,
                text_transform=lambda text: _restore_participant_labels(
                    text,
                    session,
                    anonymous_labels,
                ),
            )
            if cancel_event.is_set():
                return
            self._transition(session, cancel_event, SessionStatus.COMPLETED)
        except Exception as exc:
            if cancel_event.is_set():
                return
            try:
                self._transition(
                    session,
                    cancel_event,
                    SessionStatus.FAILED,
                    error=str(exc),
                )
            except Exception:
                return

    def _await_guidance(
        self,
        session: DiscussionSession,
        round_index: int,
        cancel_event: threading.Event,
    ) -> str | None:
        with self._guidance_lock:
            self._guidance_text = None
            self._guidance_event.clear()
        self._transition(
            session,
            cancel_event,
            SessionStatus.AWAITING_GUIDANCE,
            round_index=round_index,
        )
        self._guidance_event.wait(GUIDANCE_TIMEOUT_SECONDS)
        with self._guidance_lock:
            if cancel_event.is_set():
                return None
            guidance = self._guidance_text
            self._transition(
                session,
                cancel_event,
                SessionStatus.ROUND2_RUNNING,
                round_index=round_index,
            )
            return guidance

    def _resolve_participants(
        self,
        specs: tuple[ParticipantSpec, ...],
    ) -> list[_ResolvedParticipant]:
        resolved: list[_ResolvedParticipant] = []
        for spec in specs:
            try:
                adapter = self._adapter_factory(spec)
                detection = adapter.detect()
            except Exception as exc:
                adapter = None
                detection = DetectionResult(
                    spec.adapter_id,
                    False,
                    None,
                    "not_found",
                    str(exc),
                )
            resolved.append(_ResolvedParticipant(spec, adapter, detection))
        return resolved

    def _run_round(
        self,
        session: DiscussionSession,
        participants: Sequence[_ResolvedParticipant],
        round_index: int,
        prompt_factory: Callable[[_ResolvedParticipant], str],
        cancel_event: threading.Event,
    ) -> list[_TurnResult]:
        results: list[_TurnResult | None] = [None] * len(participants)
        results_lock = threading.Lock()
        semaphore = threading.Semaphore(MAX_CONCURRENT_PROCESSES)
        turn_ids = [
            self._begin_turn(
                session,
                participant.spec.id,
                round_index,
                (
                    participant.adapter.supports_token_stream
                    if participant.adapter is not None
                    else participant.spec.supports_token_stream
                ),
                cancel_event,
            )
            for participant in participants
        ]

        def run_one(
            index: int,
            participant: _ResolvedParticipant,
            turn_id: str | None,
        ) -> None:
            with semaphore:
                if cancel_event.is_set():
                    return
                result = self._run_turn(
                    session,
                    participant,
                    round_index,
                    prompt_factory(participant),
                    cancel_event,
                    turn_id=turn_id,
                )
                with results_lock:
                    results[index] = result

        threads = [
            threading.Thread(
                target=run_one,
                args=(index, participant, turn_ids[index]),
                name=f"discussion-turn-r{round_index}-{participant.spec.id}",
                daemon=True,
            )
            for index, participant in enumerate(participants)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return [result for result in results if result is not None]

    def _run_turn(
        self,
        session: DiscussionSession,
        participant: _ResolvedParticipant,
        round_index: int,
        prompt: str,
        cancel_event: threading.Event,
        *,
        turn_id: str | None = None,
        text_transform: Callable[[str], str] | None = None,
    ) -> _TurnResult:
        adapter = participant.adapter
        supports_token_stream = (
            adapter.supports_token_stream
            if adapter is not None
            else participant.spec.supports_token_stream
        )
        if turn_id is None:
            turn_id = self._begin_turn(
                session,
                participant.spec.id,
                round_index,
                supports_token_stream,
                cancel_event,
            )
        if turn_id is None:
            return _TurnResult(participant, None, False, "", "cancelled")
        if (
            adapter is None
            or not participant.detection.available
            or participant.detection.path is None
        ):
            error = participant.detection.error or f"{participant.spec.adapter_id} is unavailable"
            self._fail_turn(session, turn_id, error, _DeltaAccumulator(), cancel_event)
            return _TurnResult(participant, turn_id, False, "", error)

        result_success = False
        result_error: str | None = None
        for attempt in range(2):
            accumulator = _DeltaAccumulator()
            terminal = threading.Event()
            attempt_done = False
            attempt_error: str | None = None
            attempt_reason: str | None = None
            attempt_text: list[str] = []
            final_text: str | None = None

            def on_delta(
                text: str,
                accumulator: _DeltaAccumulator = accumulator,
                attempt_text: list[str] = attempt_text,
            ) -> None:
                if cancel_event.is_set():
                    return
                attempt_text.append(text)
                combined = accumulator.add(text)
                if combined:
                    self._append_delta(session, turn_id, combined, cancel_event)

            def on_done(terminal: threading.Event = terminal) -> None:
                nonlocal attempt_done
                attempt_done = True
                terminal.set()

            def on_final_text(text: str) -> None:
                nonlocal final_text
                final_text = text
                self._replace_text(session, turn_id, text, cancel_event)

            def on_usage(usage: TurnUsage) -> None:
                self._set_turn_usage(session, turn_id, usage, cancel_event)

            def on_error(
                message: str,
                terminal: threading.Event = terminal,
            ) -> None:
                nonlocal attempt_error, attempt_reason
                attempt_error = str(message)
                if isinstance(message, StreamError):
                    attempt_reason = message.reason
                terminal.set()

            def on_cancelled(terminal: threading.Event = terminal) -> None:
                terminal.set()

            try:
                # A failed agy invocation can retain its final response. Clear
                # it before every attempt so a retry cannot inherit stale text.
                adapter.take_final_text()
                invocation = adapter.build_invocation(prompt, participant.spec.model)
                run_streaming(
                    adapter,
                    invocation,
                    on_delta,
                    on_done,
                    on_error,
                    on_cancelled,
                    on_final_text=on_final_text,
                    on_usage=on_usage,
                    cancel_event=cancel_event,
                )
            except OSError as exc:
                attempt_error = str(exc)
                attempt_reason = StreamFailureReason.LAUNCH
                terminal.set()
            except Exception as exc:
                attempt_error = str(exc)
                terminal.set()

            if cancel_event.is_set():
                break
            if not terminal.is_set():
                attempt_error = "stream runner returned without a terminal callback"
            produced_text = final_text if final_text is not None else "".join(attempt_text)
            retryable = attempt_reason == StreamFailureReason.NONZERO_EXIT
            if attempt_done and attempt_error is None:
                if produced_text.strip():
                    if text_transform is not None:
                        self._replace_text(
                            session,
                            turn_id,
                            text_transform(produced_text),
                            cancel_event,
                        )
                        accumulator = _DeltaAccumulator()
                    if final_text is not None:
                        accumulator = _DeltaAccumulator()
                    result_success = self._complete_turn(
                        session, turn_id, accumulator, cancel_event
                    )
                    break
                attempt_error = "CLI exited with empty output"
                retryable = True
            if retryable and attempt == 0:
                self._replace_text(session, turn_id, "", cancel_event)
                continue
            result_error = attempt_error or "stream runner returned without a terminal callback"
            self._fail_turn(session, turn_id, result_error, accumulator, cancel_event)
            break
        return _TurnResult(
            participant,
            turn_id,
            result_success,
            _turn_text(session, turn_id),
            result_error,
        )

    def _begin_turn(
        self,
        session: DiscussionSession,
        participant_id: str,
        round_index: int,
        supports_token_stream: bool,
        cancel_event: threading.Event,
    ) -> str | None:
        with self._event_order_lock:
            if cancel_event.is_set():
                return None
            turn = session.add_turn(
                participant_id,
                round_index,
                supports_token_stream=supports_token_stream,
            )
            event = session.start_turn(turn.id)
            self._enqueue_event_locked(event)
            return turn.id

    def _append_delta(
        self,
        session: DiscussionSession,
        turn_id: str,
        text: str,
        cancel_event: threading.Event,
    ) -> bool:
        with self._event_order_lock:
            if cancel_event.is_set():
                return False
            event = session.append_delta(turn_id, text)
            self._enqueue_event_locked(event)
            return True

    def _replace_text(
        self,
        session: DiscussionSession,
        turn_id: str,
        text: str,
        cancel_event: threading.Event,
    ) -> bool:
        with self._event_order_lock:
            if cancel_event.is_set():
                return False
            event = session.replace_text(turn_id, text)
            self._enqueue_event_locked(event)
            return True

    def _set_turn_usage(
        self,
        session: DiscussionSession,
        turn_id: str,
        usage: TurnUsage,
        cancel_event: threading.Event,
    ) -> bool:
        with self._event_order_lock:
            if cancel_event.is_set():
                return False
            self._enqueue_event_locked(session.set_turn_usage(turn_id, usage))
            return True

    def _complete_turn(
        self,
        session: DiscussionSession,
        turn_id: str,
        accumulator: _DeltaAccumulator,
        cancel_event: threading.Event,
    ) -> bool:
        with self._event_order_lock:
            if cancel_event.is_set():
                return False
            remaining = accumulator.flush()
            if remaining:
                self._enqueue_event_locked(session.append_delta(turn_id, remaining))
            self._enqueue_event_locked(session.complete_turn(turn_id))
            return True

    def _fail_turn(
        self,
        session: DiscussionSession,
        turn_id: str,
        error: str,
        accumulator: _DeltaAccumulator,
        cancel_event: threading.Event,
    ) -> bool:
        with self._event_order_lock:
            if cancel_event.is_set():
                return False
            remaining = accumulator.flush()
            if remaining:
                self._enqueue_event_locked(session.append_delta(turn_id, remaining))
            self._enqueue_event_locked(session.fail_turn(turn_id, error))
            return True

    def _publish_consensus_count(
        self,
        session: DiscussionSession,
        cancel_event: threading.Event,
    ) -> ConsensusCount:
        with self._event_order_lock:
            if cancel_event.is_set():
                return ConsensusCount()
            event = session.count_consensus()
            self._enqueue_event_locked(event)
            return ConsensusCount(**event.payload)

    def _mark_consensus_reached(
        self,
        session: DiscussionSession,
        round_index: int,
        cancel_event: threading.Event,
    ) -> bool:
        with self._event_order_lock:
            if cancel_event.is_set():
                return False
            self._enqueue_event_locked(session.mark_consensus_reached(round_index))
            return True

    def _transition(
        self,
        session: DiscussionSession,
        cancel_event: threading.Event,
        status: SessionStatus,
        *,
        error: str | None = None,
        round_index: int | None = None,
    ) -> bool:
        with self._event_order_lock:
            if cancel_event.is_set():
                return False
            if status is SessionStatus.COMPLETED:
                snapshot = session.snapshot()
                snapshot["status"] = status.value
                with self._state_lock:
                    snapshot["working_directory"] = self._working_directory
                self._archive_completed_session(session.session_id, snapshot)
            event = session.transition(status, error=error, round_index=round_index)
            if event is not None:
                self._enqueue_event_locked(event)
            return True

    def _archive_completed_session(
        self,
        session_id: str,
        snapshot: dict[str, object],
    ) -> None:
        try:
            # Transcripts carry full conversation text and project paths; keep them
            # owner-only like the neutral workspace in discussion_cli.
            DISCUSSIONS_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
            base = DISCUSSIONS_DIRECTORY / session_id
            for suffix, payload in (
                (".json", json.dumps(snapshot, ensure_ascii=False, indent=2)),
                (".md", _render_discussion_markdown(snapshot)),
            ):
                path = base.with_suffix(suffix)
                path.write_text(payload, encoding="utf-8")
                path.chmod(0o600)
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("failed to archive discussion %s", session_id, exc_info=True)
            return

    def _enqueue_event_locked(self, event: DiscussionEvent) -> None:
        listener: Callable[[], None] | None = None
        with self._event_lock:
            if not self._callbacks_enabled:
                return
            was_empty = not self._events
            self._events.append(event)
            if was_empty:
                listener = self._event_listener
        if listener is not None:
            try:
                listener()
            except Exception:
                return


def _default_adapter_factory(spec: ParticipantSpec) -> CLIAdapter:
    if spec.source == "argv" or spec.source == "login_shell":
        return _CustomLineAdapter(spec)
    if spec.adapter_id == "claude":
        return ClaudeAdapter(
            cwd=spec.cwd,
            read_only=spec.read_only,
            extra_read_dirs=spec.extra_read_dirs,
            env_overrides=spec.env_overrides,
            timeout_seconds=spec.timeout_seconds,
        )
    if spec.adapter_id == "codex":
        return CodexAdapter(
            cwd=spec.cwd,
            read_only=spec.read_only,
            extra_read_dirs=spec.extra_read_dirs,
            env_overrides=spec.env_overrides,
            timeout_seconds=spec.timeout_seconds,
        )
    if spec.adapter_id == "agy":
        return AgyAdapter(
            cwd=spec.cwd,
            read_only=spec.read_only,
            extra_read_dirs=spec.extra_read_dirs,
            env_overrides=spec.env_overrides,
            timeout_seconds=spec.timeout_seconds,
        )
    raise ValueError(f"unknown built-in adapter: {spec.adapter_id}")


def _select_moderator(
    survivors: Sequence[_TurnResult],
    moderator_id: str | None,
) -> _TurnResult | None:
    if moderator_id is not None:
        for survivor in survivors:
            if survivor.participant.spec.id == moderator_id:
                return survivor
    return survivors[0] if survivors else None


def _turn_text(session: DiscussionSession, turn_id: str) -> str:
    snapshot = session.snapshot()
    for turn in snapshot["turns"]:
        if turn["id"] == turn_id:
            return str(turn["text"])
    return ""


def _anonymous_participant_label(index: int) -> str:
    """Return a stable A, B, … label for a zero-based participant index."""
    return f"參與者 {chr(ord('A') + index)}" if index < 26 else f"參與者 {index + 1}"


def _is_unanimous_consensus(
    consensus: ConsensusCount, expected_participants: int
) -> bool:
    return (
        consensus.agree
        + consensus.disagree
        + consensus.alternative
        + consensus.unparsed
        == expected_participants
        and consensus.agree >= 2
        and consensus.disagree == 0
        and consensus.alternative == 0
        and consensus.unparsed == 0
    )


def _render_discussion_markdown(snapshot: dict[str, object]) -> str:
    participants = snapshot["participants"]
    turns = snapshot["turns"]
    assert isinstance(participants, list)
    assert isinstance(turns, list)
    total_rounds = snapshot["total_rounds"]
    assert isinstance(total_rounds, int)
    labels = {
        str(participant["id"]): str(participant["label"])
        for participant in participants
        if isinstance(participant, dict)
    }
    lines = [
        f"# {snapshot['topic']}",
        datetime.now().astimezone().isoformat(),
        "參與者：" + "、".join(labels.values()),
    ]
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        text = str(turn["text"])
        participant = labels.get(str(turn["participant_id"]), str(turn["participant_id"]))
        if int(turn["round_index"]) > total_rounds:
            lines.extend(("## 主持人總結", text))
        else:
            lines.extend((f"## 第 {turn['round_index']} 輪 · {participant}", text))
    return "\n\n".join(lines) + "\n"


def _build_transcript(
    session: DiscussionSession,
    anonymous_labels: Mapping[str, str],
) -> str:
    snapshot = session.snapshot()
    sections: list[str] = []
    for turn in snapshot["turns"]:
        participant_id = str(turn["participant_id"])
        error = turn["error"]
        body = str(turn["text"])
        if error:
            body = f"{body}\n[此發言未完成]" if body else "[此發言未完成]"
        sections.append(
            f"<<<TURN participant={anonymous_labels.get(participant_id, participant_id)!r} "
            f"round={turn['round_index']} status={turn['status']}>>>\n"
            f"{body}\n<<<TURN_END>>>"
        )
    return "\n\n".join(sections)


def _restore_participant_labels(
    text: str,
    session: DiscussionSession,
    anonymous_labels: Mapping[str, str],
) -> str:
    labels = {
        anonymous_labels[participant.id]: participant.label
        for participant in session.participants
    }
    return _replace_labels(text, labels)


def _replace_labels(
    text: str,
    replacements: Mapping[str, str],
) -> str:
    labels = sorted((label for label in replacements if label), key=len, reverse=True)
    if not labels:
        return text
    pattern = re.compile(
        f"(?:{'|'.join(re.escape(label) for label in labels)})(?![A-Za-z0-9])"
    )
    return pattern.sub(lambda match: replacements[match.group(0)], text)


def _attachment_dirs(attachments: Sequence[str]) -> tuple[str, ...]:
    """Distinct absolute directories holding the existing attachment files.

    Missing paths are ignored (mirrors ``build_attachment_block``); only the
    folder each surviving file lives in is returned, deduplicated and in
    stable first-seen order.
    """
    seen: set[str] = set()
    dirs: list[str] = []
    for raw in attachments:
        path = Path(str(raw))
        if not path.is_file():
            continue
        directory = str(path.resolve().parent)
        if directory not in seen:
            seen.add(directory)
            dirs.append(directory)
    return tuple(dirs)


def build_attachment_block(attachments: Sequence[str], language: str) -> str:
    """Append-only image section for the prompt sent to each CLI.

    Returns ``""`` when none of the paths point at an existing file, so the
    discussion proceeds unchanged. Existing-file paths are resolved to absolute
    form; missing paths are skipped rather than aborting the whole session.
    """
    resolved: list[str] = []
    for raw in attachments:
        path = Path(str(raw))
        if path.is_file():
            resolved.append(str(path.resolve()))
    if not resolved:
        return ""
    header = _t(language, "discussion_prompt_attachment_header")
    return "\n\n" + header + "\n" + "\n".join(resolved)
