# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for scripts/build_blog.py using isolated temporary directories."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_blog", Path(__file__).resolve().parent.parent / "scripts" / "build_blog.py"
)
assert _SPEC is not None and _SPEC.loader is not None
build_blog = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = build_blog
_SPEC.loader.exec_module(build_blog)

SITEMAP_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
    '        xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
    "  <url>\n"
    "    <loc>https://example.invalid/</loc>\n"
    "  </url>\n"
    "<!-- blog:start -->\n"
    "<!-- blog:end -->\n"
    "</urlset>\n"
)

JSON_LD_RE = re.compile(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', re.S)


def _setup_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    source_dir = tmp_path / "site" / "blog"
    docs_dir = tmp_path / "docs"
    source_dir.mkdir(parents=True)
    docs_dir.mkdir(parents=True)
    sitemap_path = docs_dir / "sitemap.xml"
    sitemap_path.write_text(SITEMAP_TEMPLATE, encoding="utf-8")

    monkeypatch.setattr(build_blog, "SOURCE_DIR", source_dir)
    monkeypatch.setattr(build_blog, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(build_blog, "SITEMAP_PATH", sitemap_path)
    return source_dir, docs_dir, sitemap_path


def _write_post(
    source_dir: Path,
    slug: str,
    lang: str,
    *,
    title: str,
    description: str,
    date: str,
    updated: str | None = None,
    related: str | None = None,
    body: str,
) -> Path:
    post_dir = source_dir / slug
    post_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"title: {title}",
        f"description: {description}",
        f"date: {date}",
    ]
    if updated is not None:
        lines.append(f"updated: {updated}")
    if related is not None:
        lines.append(f"related: {related}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    path = post_dir / f"{lang}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _parse_json_ld(html_text: str) -> list[dict[str, Any]]:
    return [json.loads(match) for match in JSON_LD_RE.findall(html_text)]


def test_empty_blog_creates_no_list_pages_and_passes_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir, docs_dir, sitemap_path = _setup_workspace(tmp_path, monkeypatch)
    (source_dir / "README.md").write_text("# Blog guide\n", encoding="utf-8")

    assert build_blog.main([]) == 0
    assert build_blog.main(["--check"]) == 0
    assert not (docs_dir / "blog").exists()
    assert sitemap_path.read_text(encoding="utf-8") == SITEMAP_TEMPLATE


def test_bilingual_article_renders_seo_cards_escaping_and_sitemap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir, docs_dir, sitemap_path = _setup_workspace(tmp_path, monkeypatch)

    _write_post(
        source_dir,
        "older-post",
        "en",
        title="Older Post",
        description="First post summary",
        date="2026-10-01",
        body="First paragraph.\n\nSecond paragraph.",
    )
    _write_post(
        source_dir,
        "new-post",
        "en",
        title="New Post",
        description="New post summary",
        date="2026-11-20",
        updated="2026-11-22",
        related="older-post",
        body=(
            "Intro paragraph.\n\n"
            "<script>alert(1)</script>\n\n"
            "| Tool | Support |\n"
            "| --- | --- |\n"
            "| Claude | Yes |\n"
        ),
    )
    _write_post(
        source_dir,
        "new-post",
        "zh-TW",
        title="新文章",
        description="繁體中文摘要",
        date="2026-11-20",
        related="older-post",
        body="第一段內容。\n\n第二段內容。",
    )

    assert build_blog.main([]) == 0
    assert build_blog.main(["--check"]) == 0

    en_html = (docs_dir / "blog" / "new-post" / "index.html").read_text(encoding="utf-8")
    tw_html = (docs_dir / "zh-TW" / "blog" / "new-post" / "index.html").read_text(encoding="utf-8")

    assert en_html.startswith(build_blog.BANNER)
    assert tw_html.startswith(build_blog.BANNER)

    site = build_blog._site_root()
    assert f'<link rel="canonical" href="{site}blog/new-post/" />' in en_html
    assert f'<link rel="canonical" href="{site}zh-TW/blog/new-post/" />' in tw_html
    for page in (en_html, tw_html):
        assert f'<link rel="alternate" hreflang="en" href="{site}blog/new-post/" />' in page
        assert (
            f'<link rel="alternate" hreflang="zh-TW" href="{site}zh-TW/blog/new-post/" />' in page
        )
        assert f'<link rel="alternate" hreflang="x-default" href="{site}blog/new-post/" />' in page
        assert page.count('class="blog-cta-card"') == 2
        assert "#install" in page
        assert "https://github.com/aqua5230/usage" in page

    # Raw HTML in markdown must be escaped.
    assert "<script>alert(1)</script>" not in en_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in en_html
    assert "<table>" in en_html

    # Download card placement: first after first </p>, second at end before related section.
    first_p_end = en_html.index("</p>")
    first_card = en_html.index('class="blog-cta-card"')
    second_card = en_html.index('class="blog-cta-card"', first_card + 1)
    related_pos = en_html.index('class="related-section"')
    assert first_p_end < first_card < second_card < related_pos

    # Related link falls back to en when target language lacks a translation.
    assert 'href="../../blog/older-post/"' in en_html
    assert 'href="../../../blog/older-post/"' in tw_html

    # JSON-LD Article + BreadcrumbList parse cleanly.
    ld_blocks = _parse_json_ld(en_html)
    types = {block["@type"] for block in ld_blocks}
    assert types == {"Article", "BreadcrumbList"}
    article_ld = next(block for block in ld_blocks if block["@type"] == "Article")
    assert article_ld["author"] == {
        "@type": "Person",
        "name": "lollapalooza",
        "url": "https://github.com/aqua5230",
    }
    assert article_ld["datePublished"] == "2026-11-20"
    assert article_ld["dateModified"] == "2026-11-22"

    # List page sorted newest -> oldest, and older-post has no related section.
    en_list = (docs_dir / "blog" / "index.html").read_text(encoding="utf-8")
    assert en_list.index("new-post/") < en_list.index("older-post/")
    older_html = (docs_dir / "blog" / "older-post" / "index.html").read_text(encoding="utf-8")
    assert 'class="related-section"' not in older_html

    # Sitemap contains blog URLs inside markers and keeps existing URL outside.
    sitemap_text = sitemap_path.read_text(encoding="utf-8")
    assert "<loc>https://example.invalid/</loc>" in sitemap_text
    assert f"<loc>{site}blog/</loc>" in sitemap_text
    assert f"<loc>{site}zh-TW/blog/</loc>" in sitemap_text
    assert f"<loc>{site}blog/new-post/</loc>" in sitemap_text
    assert f"<loc>{site}zh-TW/blog/new-post/</loc>" in sitemap_text
    assert "<lastmod>2026-11-22</lastmod>" in sitemap_text


def test_check_returns_1_when_source_modified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_dir, _, _ = _setup_workspace(tmp_path, monkeypatch)
    en_md = _write_post(
        source_dir,
        "sample-post",
        "en",
        title="Initial Title",
        description="Initial description",
        date="2026-11-20",
        body="Initial body.",
    )
    assert build_blog.main([]) == 0
    assert build_blog.main(["--check"]) == 0

    en_md.write_text(
        en_md.read_text(encoding="utf-8").replace("Initial body.", "Edited body."),
        encoding="utf-8",
    )
    assert build_blog.main(["--check"]) == 1
    assert "sample-post" in capsys.readouterr().out


def test_check_returns_1_on_orphan_page_after_source_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_dir, docs_dir, _ = _setup_workspace(tmp_path, monkeypatch)
    _write_post(
        source_dir,
        "sample-post",
        "en",
        title="English",
        description="EN desc",
        date="2026-11-20",
        body="EN body.",
    )
    tw_md = _write_post(
        source_dir,
        "sample-post",
        "zh-TW",
        title="中文",
        description="ZH desc",
        date="2026-11-20",
        body="中文內容。",
    )
    assert build_blog.main([]) == 0
    assert build_blog.main(["--check"]) == 0

    tw_md.unlink()
    assert build_blog.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert str(docs_dir / "zh-TW" / "blog" / "sample-post" / "index.html") in out

    # Rebuilding prunes the orphan files and makes --check pass again.
    assert build_blog.main([]) == 0
    assert not (docs_dir / "zh-TW" / "blog").exists()
    assert build_blog.main(["--check"]) == 0


def test_invalid_frontmatter_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_dir, _, _ = _setup_workspace(tmp_path, monkeypatch)
    _write_post(
        source_dir,
        "bad-date",
        "en",
        title="Bad Date",
        description="Desc",
        date="2026-99-99",
        body="Body.",
    )
    with pytest.raises(ValueError, match="invalid date"):
        build_blog.main([])


def test_heading_ids_cjk_and_duplicates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_dir, docs_dir, _ = _setup_workspace(tmp_path, monkeypatch)
    _write_post(
        source_dir,
        "headings-post",
        "zh-TW",
        title="標題測試",
        description="測試 h2 id 規則",
        date="2026-11-23",
        body=(
            "前言。\n\n"
            "## 5 小時額度和每週額度差在哪？\n\n第一節。\n\n"
            "## 重複標題\n\n第二節。\n\n"
            "## 重複標題\n\n第三節。\n\n"
            "## 重複標題\n\n第四節。\n"
        ),
    )
    assert build_blog.main([]) == 0
    article_html = (docs_dir / "zh-TW" / "blog" / "headings-post" / "index.html").read_text(
        encoding="utf-8"
    )

    assert '<h2 id="5-小時額度和每週額度差在哪">5 小時額度和每週額度差在哪？</h2>' in article_html
    assert '<h2 id="重複標題">重複標題</h2>' in article_html
    assert '<h2 id="重複標題-2">重複標題</h2>' in article_html
    assert '<h2 id="重複標題-3">重複標題</h2>' in article_html
    assert 'href="#5-小時額度和每週額度差在哪"' in article_html
    assert 'href="#重複標題"' in article_html
    assert 'href="#重複標題-2"' in article_html
    assert 'href="#重複標題-3"' in article_html


def test_toc_omitted_when_fewer_than_three_h2s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir, docs_dir, _ = _setup_workspace(tmp_path, monkeypatch)
    _write_post(
        source_dir,
        "short-post",
        "en",
        title="Short Post",
        description="Only two sections",
        date="2026-11-23",
        body="Intro.\n\n## First Section\n\nText.\n\n## Second Section\n\nText.\n",
    )
    assert build_blog.main([]) == 0
    article_html = (docs_dir / "blog" / "short-post" / "index.html").read_text(encoding="utf-8")

    assert '<h2 id="first-section">First Section</h2>' in article_html
    assert '<h2 id="second-section">Second Section</h2>' in article_html
    assert '<aside class="toc-rail">' not in article_html
    assert '<details class="toc-mobile">' not in article_html
    assert '<aside class="news-rail"' in article_html


def test_toc_links_match_body_h2_and_exclude_related_and_cta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir, docs_dir, _ = _setup_workspace(tmp_path, monkeypatch)
    _write_post(
        source_dir,
        "target-post",
        "en",
        title="Target Post",
        description="Related target",
        date="2026-11-20",
        body="Target body.",
    )
    _write_post(
        source_dir,
        "full-post",
        "en",
        title="Full Post",
        description="Has three sections and related",
        date="2026-11-23",
        related="target-post",
        body=(
            "Intro.\n\n"
            "## Alpha One\n\nParagraph.\n\n"
            "## Beta `Two`!\n\nParagraph.\n\n"
            "## Gamma Three?\n\nParagraph.\n"
        ),
    )
    assert build_blog.main([]) == 0

    article_html = (docs_dir / "blog" / "full-post" / "index.html").read_text(encoding="utf-8")
    list_html = (docs_dir / "blog" / "index.html").read_text(encoding="utf-8")

    assert '<aside class="toc-rail">' in article_html
    assert '<details class="toc-mobile">' in article_html
    assert "<summary>In this article</summary>" in article_html

    toc_block = article_html.split('<aside class="toc-rail">', 1)[1].split("</aside>", 1)[0]
    toc_hrefs = re.findall(r'href="#([^"]+)"', toc_block)
    assert toc_hrefs == ["alpha-one", "beta-two", "gamma-three"]
    for heading_id in toc_hrefs:
        assert f'<h2 id="{heading_id}">' in article_html

    assert "Related Articles" not in toc_block
    assert build_blog.UI_STRINGS["en"]["card_title"] not in toc_block
    assert "<h2>Related Articles</h2>" in article_html

    # List page must not include article rails or news fetch script.
    assert '<aside class="toc-rail">' not in list_html
    assert '<details class="toc-mobile">' not in list_html
    assert '<aside class="news-rail"' not in list_html
    assert "ai-updates/data.json" not in list_html

    # Article page includes news rail (hidden initially) and matchMedia guard without innerHTML.
    assert '<aside class="news-rail" aria-label="AI Update Daily" hidden>' in article_html
    assert 'window.matchMedia("(min-width: 1440px)")' in article_html
    assert "innerHTML" not in article_html


def test_ui_strings_include_toc_and_news_keys_for_all_langs() -> None:
    for lang in build_blog.LANGS:
        ui = build_blog.UI_STRINGS[lang]
        assert ui["toc_title"]
        assert ui["news_title"]
        assert ui["news_all"]
