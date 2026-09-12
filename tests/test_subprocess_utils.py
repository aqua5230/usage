# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import subprocess
import sys

import pytest

from usage_common.subprocess_utils import hidden_console_kwargs


def test_hidden_console_kwargs_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    assert hidden_console_kwargs() == {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)
    }


def test_hidden_console_kwargs_on_other_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")

    assert hidden_console_kwargs() == {}
