from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from panels import share_card

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PNG_B64 = base64.b64encode(PNG).decode()


def _message(**overrides: object) -> dict[str, object]:
    message: dict[str, object] = {
        "action": "share_pal_card",
        "target": "threads",
        "name": "tuanli",
        "png": PNG_B64,
        "text": "我在 usage 遇到隱藏版「智團狸」了！",
    }
    message.update(overrides)
    return message


def test_intent_url_carries_text_and_repo_link_on_a_fixed_host() -> None:
    url = share_card.intent_url("threads", "我在 usage & 遇到")

    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "www.threads.com", "/intent/post")
    assert parse_qs(parts.query) == {"text": ["我在 usage & 遇到"], "url": [share_card.REPO_URL]}
    assert urlsplit(share_card.intent_url("x", "hi")).netloc == "x.com"


def test_parse_accepts_a_well_formed_message() -> None:
    assert share_card.parse(_message()) == (
        "threads",
        "tuanli",
        PNG,
        "我在 usage 遇到隱藏版「智團狸」了！",
    )


def test_parse_rejects_unknown_targets_names_and_non_png_data() -> None:
    assert share_card.parse(_message(target="mail")) is None
    assert share_card.parse(_message(name="../tuanli")) is None
    assert share_card.parse(_message(text=None)) is None
    assert share_card.parse(_message(png=base64.b64encode(b"GIF89a").decode())) is None
    assert share_card.parse(_message(png="not base64!")) is None


def test_free_path_never_overwrites_an_earlier_save(tmp_path: Path) -> None:
    first = share_card.free_path(tmp_path, "usage-tuanli")
    assert first.name == "usage-tuanli.png"
    first.write_bytes(PNG)

    assert share_card.free_path(tmp_path, "usage-tuanli").name == "usage-tuanli (2).png"
