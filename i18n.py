from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from usage_lang import detect_lang


def packaged_resource_path(filename: str, source_mode_path: Path) -> Path:
    """Resolve a data file across source-mode and py2app-bundle layouts.

    py2app declares data files via setup_app.py ``OPTIONS["resources"]`` and
    copies them to ``Contents/Resources/`` — adjacent to ``lib/python313.zip``,
    not inside it. py2app injects the ``RESOURCEPATH`` env var at launch
    pointing at that directory; we prefer it when present.

    Why this exists: in py2app builds this module is compiled into
    ``lib/python313.zip``, so ``Path(__file__).with_name("i18n.json")``
    resolves to ``lib/python313.zip/i18n.json`` — an invalid path through
    the zipfile that raises ``NotADirectoryError`` at first read. In source
    mode (and tests) ``RESOURCEPATH`` is unset and the source-adjacent
    fallback path is correct.

    The callers pass the source-mode path explicitly (as the literal
    ``Path(__file__).with_name("...")``) so that
    ``tests/test_packaged_resources.py`` can still statically detect every
    declared resource and enforce that ``setup_app.py`` lists it.
    """
    resource_root = os.environ.get("RESOURCEPATH")
    if resource_root:
        bundled = Path(resource_root) / filename
        if bundled.exists():
            return bundled
    return source_mode_path


I18N_PATH = packaged_resource_path("i18n.json", Path(__file__).with_name("i18n.json"))


@lru_cache(maxsize=1)
def _load_i18n_bundle() -> dict[str, dict[str, str]]:
    data = json.loads(I18N_PATH.read_text(encoding="utf-8"))
    return {
        str(lang): {str(key): str(value) for key, value in values.items()}
        for lang, values in data.items()
    }


def _t(language: str, key: str, **kwargs: object) -> str:
    bundle = _load_i18n_bundle()
    table = bundle.get(language) or bundle["en"]
    template = table.get(key) or bundle["en"].get(key) or key
    return template.format(**kwargs)


def t(key: str, **kwargs: object) -> str:
    return _t(detect_lang(), key, **kwargs)
