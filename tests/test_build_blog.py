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

_SITE_SPEC = importlib.util.spec_from_file_location(
    "build_site_pages", Path(__file__).resolve().parent.parent / "scripts" / "build_site_pages.py"
)
assert _SITE_SPEC is not None and _SITE_SPEC.loader is not None
build_site_pages = importlib.util.module_from_spec(_SITE_SPEC)
sys.modules[_SITE_SPEC.name] = build_site_pages
_SITE_SPEC.loader.exec_module(build_site_pages)

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

INDEX_TEMPLATE = (
    "<!doctype html>\n"
    '<html lang="en">\n'
    "<head>\n"
    "<title>usage</title>\n"
    '<link rel="canonical" href="https://aqua5230.github.io/usage/" />\n'
    '<meta property="og:title" content="usage" />\n'
    '<meta property="og:description" content="desc" />\n'
    '<meta property="og:url" content="https://aqua5230.github.io/usage/" />\n'
    '<script type="application/ld+json">\n'
    "{\n"
    '  "description": "desc",\n'
    '  "url": "https://aqua5230.github.io/usage/",\n'
    '  "inLanguage": "en",\n'
    '  "name": "usage"\n'
    "}\n"
    "</script>\n"
    "</head>\n"
    "<body>\n"
    '<svg class="brand-symbols"><symbol id="usage-ring"></symbol></svg>\n'
    '<a class="brand"><span class="brand-dot"><svg class="brand-cat"></svg></span>usage</a>\n'
    '<section id="latest-posts">\n'
    "<!-- latest-posts:start -->\n"
    "<!-- latest-posts:end -->\n"
    "</section>\n"
    "</body>\n"
    "</html>\n"
)

JSON_LD_RE = re.compile(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', re.S)


def _setup_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    source_dir = tmp_path / "site" / "blog"
    docs_dir = tmp_path / "docs"
    source_dir.mkdir(parents=True)
    docs_dir.mkdir(parents=True)
    sitemap_path = docs_dir / "sitemap.xml"
    sitemap_path.write_text(SITEMAP_TEMPLATE, encoding="utf-8")
    index_path = docs_dir / "index.html"
    index_path.write_text(INDEX_TEMPLATE, encoding="utf-8")

    monkeypatch.setattr(build_blog, "SOURCE_DIR", source_dir)
    monkeypatch.setattr(build_blog, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(build_blog, "SITEMAP_PATH", sitemap_path)
    monkeypatch.setattr(build_blog, "INDEX_PATH", index_path)
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
    image: str | None = None,
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
    if image is not None:
        lines.append(f"image: {image}")
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
    assert (docs_dir / "index.html").read_text(encoding="utf-8") == INDEX_TEMPLATE


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
    # The header reuses the landing page's logo instead of a separate mark.
    for page in (en_html, tw_html):
        assert '<svg class="brand-symbols"><symbol id="usage-ring"></symbol></svg>' in page
        assert '<span class="brand-dot"><svg class="brand-cat"></svg></span>usage</a>' in page

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


def test_homepage_latest_posts_top_three_hrefs_hidden_and_language_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir, docs_dir, _ = _setup_workspace(tmp_path, monkeypatch)
    _write_post(
        source_dir,
        "oldest-post",
        "en",
        title="Oldest Post",
        description="Should not appear on homepage",
        date="2026-10-01",
        body="Body 1.",
    )
    _write_post(
        source_dir,
        "alpha-same-day",
        "en",
        title="Alpha & <Beta>",
        description="Same day earlier slug",
        date="2026-11-10",
        body="Body 2.",
    )
    _write_post(
        source_dir,
        "zeta-same-day",
        "en",
        title="Zeta Same Day",
        description="Same day later slug",
        date="2026-11-10",
        body="Body 3.",
    )
    _write_post(
        source_dir,
        "newest-post",
        "en",
        title="Newest Post",
        description="Latest <summary>",
        date="2026-11-20",
        body="Body 4.",
    )
    _write_post(
        source_dir,
        "tw-only",
        "zh-TW",
        title="繁中文章",
        description="繁中摘要",
        date="2026-11-18",
        body="內文。",
    )

    assert build_blog.main([]) == 0
    assert build_blog.main(["--check"]) == 0

    index_html = (docs_dir / "index.html").read_text(encoding="utf-8")
    assert '<div class="latest-posts" data-posts-lang="en">' in index_html
    assert '<div class="latest-posts" data-posts-lang="zh-TW" hidden>' in index_html
    assert 'data-posts-lang="ja"' not in index_html

    en_block = index_html.split('<div class="latest-posts" data-posts-lang="en">', 1)[1].split(
        "</div>", 1
    )[0]
    assert "oldest-post" not in en_block
    assert en_block.count('class="latest-post"') == 3
    assert (
        en_block.index('href="blog/newest-post/"')
        < en_block.index('href="blog/zeta-same-day/"')
        < en_block.index('href="blog/alpha-same-day/"')
    )
    assert '<time datetime="2026-11-20">2026-11-20</time>' in en_block
    assert "<h3>Alpha &amp; &lt;Beta&gt;</h3>" in en_block
    assert "<p>Latest &lt;summary&gt;</p>" in en_block

    tw_block = index_html.split('<div class="latest-posts" data-posts-lang="zh-TW" hidden>', 1)[
        1
    ].split("</div>", 1)[0]
    assert tw_block.count('class="latest-post"') == 1
    assert 'href="zh-TW/blog/tw-only/"' in tw_block

    tw_page = build_site_pages.render(
        index_html, "zh-TW", {"meta_title": "標題", "meta_desc": "描述"}
    )
    assert tw_page.count("data-posts-lang") == 1
    assert '<div class="latest-posts" data-posts-lang="zh-TW">' in tw_page
    assert 'href="../zh-TW/blog/tw-only/"' in tw_page

    ja_page = build_site_pages.render(
        index_html, "ja", {"meta_title": "タイトル", "meta_desc": "説明"}
    )
    assert ja_page.count("data-posts-lang") == 1
    assert '<div class="latest-posts" data-posts-lang="en">' in ja_page
    assert 'href="../blog/newest-post/"' in ja_page


def test_homepage_missing_markers_raises_and_stale_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_dir, docs_dir, _ = _setup_workspace(tmp_path, monkeypatch)
    index_path = docs_dir / "index.html"
    index_path.write_text("<html><body>No markers</body></html>", encoding="utf-8")

    with pytest.raises(ValueError, match="latest-posts"):
        build_blog.main([])

    index_path.write_text(INDEX_TEMPLATE, encoding="utf-8")
    _write_post(
        source_dir,
        "sample-post",
        "en",
        title="Sample",
        description="Sample desc",
        date="2026-11-20",
        body="Body.",
    )
    assert build_blog.main([]) == 0
    assert build_blog.main(["--check"]) == 0

    index_path.write_text(
        index_path.read_text(encoding="utf-8").replace("<h3>Sample</h3>", "<h3>Stale</h3>"),
        encoding="utf-8",
    )
    assert build_blog.main(["--check"]) == 1
    assert str(index_path) in capsys.readouterr().out


def test_images_copied_once_as_bytes_and_rewritten_per_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir, docs_dir, sitemap_path = _setup_workspace(tmp_path, monkeypatch)
    post_dir = source_dir / "pond-post"
    post_dir.mkdir(parents=True)

    pond_bytes = b"\xff\xd8\xff\xe0FAKEJPEG"
    diagram_bytes = b"<svg></svg>"
    (post_dir / "pond.jpg").write_bytes(pond_bytes)
    (post_dir / "Diagram.SVG").write_bytes(diagram_bytes)
    (post_dir / "notes.txt").write_text("ignored", encoding="utf-8")

    _write_post(
        source_dir,
        "pond-post",
        "en",
        title="Pond Post",
        description="With images",
        date="2026-11-24",
        body="![Pond](pond.jpg)\n\n![Diagram](Diagram.SVG)\n",
    )
    _write_post(
        source_dir,
        "pond-post",
        "zh-TW",
        title="池塘文章",
        description="附圖片",
        date="2026-11-24",
        body="![池塘](pond.jpg)\n\n![圖表](Diagram.SVG)\n",
    )

    outputs, _, _ = build_blog.build_outputs(
        source_dir,
        docs_dir,
        sitemap_path.read_text(encoding="utf-8"),
        (docs_dir / "index.html").read_text(encoding="utf-8"),
    )
    pond_out = docs_dir / "blog" / "pond-post" / "pond.jpg"
    diagram_out = docs_dir / "blog" / "pond-post" / "Diagram.SVG"
    assert outputs[pond_out] == pond_bytes
    assert isinstance(outputs[pond_out], bytes)
    assert outputs[diagram_out] == diagram_bytes
    assert (docs_dir / "blog" / "pond-post" / "notes.txt") not in outputs
    assert (docs_dir / "zh-TW" / "blog" / "pond-post" / "pond.jpg") not in outputs

    assert build_blog.main([]) == 0
    assert pond_out.read_bytes() == pond_bytes
    assert diagram_out.read_bytes() == diagram_bytes
    assert not (docs_dir / "zh-TW" / "blog" / "pond-post" / "pond.jpg").exists()
    assert not (docs_dir / "blog" / "pond-post" / "notes.txt").exists()

    en_html = (docs_dir / "blog" / "pond-post" / "index.html").read_text(encoding="utf-8")
    tw_html = (docs_dir / "zh-TW" / "blog" / "pond-post" / "index.html").read_text(encoding="utf-8")
    assert '<img src="pond.jpg" alt="Pond" />' in en_html
    assert '<img src="Diagram.SVG" alt="Diagram" />' in en_html
    assert '<img src="../../../blog/pond-post/pond.jpg" alt="池塘" />' in tw_html
    assert '<img src="../../../blog/pond-post/Diagram.SVG" alt="圖表" />' in tw_html


def test_external_and_root_relative_image_srcs_left_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir, docs_dir, _ = _setup_workspace(tmp_path, monkeypatch)
    _write_post(
        source_dir,
        "remote-imgs",
        "zh-TW",
        title="外部圖片",
        description="不改寫外部或根路徑圖片",
        date="2026-11-24",
        body=(
            "![HTTPS](https://example.com/a.png)\n\n"
            "![HTTP](http://example.com/b.jpg)\n\n"
            "![Root](/assets/c.webp)\n"
        ),
    )

    assert build_blog.main([]) == 0
    tw_html = (docs_dir / "zh-TW" / "blog" / "remote-imgs" / "index.html").read_text(
        encoding="utf-8"
    )
    assert '<img src="https://example.com/a.png" alt="HTTPS" />' in tw_html
    assert '<img src="http://example.com/b.jpg" alt="HTTP" />' in tw_html
    assert '<img src="/assets/c.webp" alt="Root" />' in tw_html


def test_missing_body_or_frontmatter_image_raises_value_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir, _, _ = _setup_workspace(tmp_path, monkeypatch)
    _write_post(
        source_dir,
        "broken-body",
        "en",
        title="Broken Body",
        description="Missing body image",
        date="2026-11-24",
        body="![Missing](typo.png)\n",
    )

    with pytest.raises(ValueError, match=r"broken-body/en\.md.*typo\.png"):
        build_blog.main([])

    (source_dir / "broken-body" / "en.md").unlink()
    fm_md = _write_post(
        source_dir,
        "broken-fm",
        "zh-TW",
        title="Broken Frontmatter",
        description="Missing frontmatter image",
        date="2026-11-24",
        image="missing-cover.webp",
        body="No body images.\n",
    )

    with pytest.raises(ValueError) as exc_info:
        build_blog.main([])
    msg = str(exc_info.value)
    assert str(fm_md) in msg
    assert "missing-cover.webp" in msg


def test_frontmatter_image_overrides_og_twitter_jsonld_and_omits_dimensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir, docs_dir, _ = _setup_workspace(tmp_path, monkeypatch)
    (source_dir / "with-cover").mkdir(parents=True)
    (source_dir / "with-cover" / "cover.PNG").write_bytes(b"\x89PNG\r\n\x1a\n")

    _write_post(
        source_dir,
        "with-cover",
        "zh-TW",
        title="有封面",
        description="自訂封面",
        date="2026-11-24",
        image="cover.PNG",
        body="內文。\n",
    )
    _write_post(
        source_dir,
        "no-cover",
        "en",
        title="No Cover",
        description="Default OG",
        date="2026-11-24",
        body="Body.\n",
    )

    assert build_blog.main([]) == 0

    site = build_blog._site_root()
    cover_url = f"{site}blog/with-cover/cover.PNG"
    with_cover_html = (docs_dir / "zh-TW" / "blog" / "with-cover" / "index.html").read_text(
        encoding="utf-8"
    )
    assert f'<meta property="og:image" content="{cover_url}" />' in with_cover_html
    assert f'<meta name="twitter:image" content="{cover_url}" />' in with_cover_html
    assert 'property="og:image:width"' not in with_cover_html
    assert 'property="og:image:height"' not in with_cover_html
    article_ld = next(
        block for block in _parse_json_ld(with_cover_html) if block["@type"] == "Article"
    )
    assert article_ld["image"] == cover_url

    default_url = f"{site}{build_blog.OG_IMAGE_PATH}"
    no_cover_html = (docs_dir / "blog" / "no-cover" / "index.html").read_text(encoding="utf-8")
    assert f'<meta property="og:image" content="{default_url}" />' in no_cover_html
    assert f'<meta name="twitter:image" content="{default_url}" />' in no_cover_html
    assert '<meta property="og:image:width" content="1200" />' in no_cover_html
    assert '<meta property="og:image:height" content="630" />' in no_cover_html
    no_cover_ld = next(
        block for block in _parse_json_ld(no_cover_html) if block["@type"] == "Article"
    )
    assert no_cover_ld["image"] == default_url


def test_run_build_check_detects_modified_and_orphan_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_dir, docs_dir, _ = _setup_workspace(tmp_path, monkeypatch)
    post_dir = source_dir / "img-check"
    post_dir.mkdir(parents=True)
    src_img = post_dir / "chart.png"
    src_img.write_bytes(b"\x89PNG\r\n\x1a\nv1")

    _write_post(
        source_dir,
        "img-check",
        "en",
        title="Image Check",
        description="Binary check",
        date="2026-11-24",
        body="![Chart](chart.png)\n",
    )

    assert build_blog.run_build(check=False) == 0
    assert build_blog.run_build(check=True) == 0

    dst_img = docs_dir / "blog" / "img-check" / "chart.png"
    src_img.write_bytes(b"\x89PNG\r\n\x1a\nv2")
    assert build_blog.run_build(check=True) == 1
    assert str(dst_img) in capsys.readouterr().out

    assert build_blog.run_build(check=False) == 0
    assert build_blog.run_build(check=True) == 0

    # Removing image from source leaves an orphan in docs/ until rebuilt.
    src_img.unlink()
    (post_dir / "en.md").write_text(
        "---\ntitle: Image Check\ndescription: Binary check\ndate: 2026-11-24\n---\n\nNo img.\n",
        encoding="utf-8",
    )
    assert build_blog.run_build(check=True) == 1
    assert str(dst_img) in capsys.readouterr().out
    assert build_blog.run_build(check=False) == 0
    assert not dst_img.exists()
    assert build_blog.run_build(check=True) == 0


def test_html_body_image_becomes_live_embed_with_full_screen_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir, docs_dir, _ = _setup_workspace(tmp_path, monkeypatch)
    post_dir = source_dir / "live-post"
    post_dir.mkdir(parents=True)
    page_bytes = b"<!doctype html><canvas></canvas>"
    (post_dir / "pond.html").write_bytes(page_bytes)
    _write_post(
        source_dir,
        "live-post",
        "zh-TW",
        title="會動的池塘",
        description="嵌入網頁",
        date="2026-11-25",
        body="![夜裡的池塘](pond.html)\n",
    )

    assert build_blog.main([]) == 0
    assert (docs_dir / "blog" / "live-post" / "pond.html").read_bytes() == page_bytes
    tw_html = (docs_dir / "zh-TW" / "blog" / "live-post" / "index.html").read_text(encoding="utf-8")
    src = "../../../blog/live-post/pond.html"
    assert f'<iframe src="{src}" title="夜裡的池塘" loading="lazy"></iframe>' in tw_html
    assert f'<a href="{src}" target="_blank" rel="noopener">全螢幕打開 ↗</a>' in tw_html
    assert "<img" not in tw_html.split('class="prose"')[1].split("</div>")[0]
    assert build_blog.main(["--check"]) == 0
