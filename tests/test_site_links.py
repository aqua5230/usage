# SPDX-License-Identifier: AGPL-3.0-only

import pytest

from usage_common.site_links import blog_url


@pytest.mark.parametrize(
    ("language", "path"),
    [
        ("zh-TW", "/zh-TW/blog/"),
        ("zh-CN", "/zh-TW/blog/"),
        ("en", "/blog/"),
        ("ja", "/blog/"),
        ("ko", "/blog/"),
    ],
)
def test_blog_url(language: str, path: str) -> None:
    assert blog_url(language) == f"https://getusage.app{path}"
