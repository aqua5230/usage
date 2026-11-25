# SPDX-License-Identifier: AGPL-3.0-only


def blog_url(language: str) -> str:
    if language in {"zh-TW", "zh-CN"}:
        return "https://getusage.app/zh-TW/blog/"
    return "https://getusage.app/blog/"
