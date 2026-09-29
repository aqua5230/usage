# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import wave
from pathlib import Path

from menubar import notify

ROOT = Path(__file__).resolve().parents[1]


class _FakeSound:
    @staticmethod
    def defaultSound() -> str:
        return "default"

    @staticmethod
    def soundNamed_(name: str) -> str:
        return f"named:{name}"


def test_warn_and_depleted_use_uhoh_but_restored_keeps_default() -> None:
    assert notify.notification_sound(_FakeSound, "warn") == "named:usage_uhoh.wav"
    assert notify.notification_sound(_FakeSound, "depleted") == "named:usage_uhoh.wav"
    assert notify.notification_sound(_FakeSound, "restored") == "default"


def test_alert_sound_is_bundled_and_short() -> None:
    sound = ROOT / "assets" / notify.ALERT_SOUND
    assert f"assets/{notify.ALERT_SOUND}" in (ROOT / "setup_app.py").read_text()
    with wave.open(str(sound)) as w:
        assert w.getnframes() / w.getframerate() < 30
