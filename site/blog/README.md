# usage Blog Authoring Guide

Blog posts live under `site/blog/<slug>/<lang>.md` and are compiled into static HTML under `docs/` by `scripts/build_blog.py`.

## Directory Layout

Each post gets its own `<slug>` directory (lowercase kebab-case, e.g. `site/blog/token-saver-benchmark/`), containing one Markdown file per language you want to publish:

- `en.md` → `docs/blog/<slug>/index.html`
- `zh-TW.md` → `docs/zh-TW/blog/<slug>/index.html`
- `zh-CN.md` → `docs/zh-CN/blog/<slug>/index.html`
- `ja.md` → `docs/ja/blog/<slug>/index.html`
- `ko.md` → `docs/ko/blog/<slug>/index.html`

Only languages with a source `.md` file are generated. List pages (`docs/blog/index.html` and `docs/<lang>/blog/index.html`) are generated automatically for languages that have at least one published post, sorted newest to oldest.

## Frontmatter Format

Every `.md` file must start with `---`-delimited `key: value` lines (parsed directly without YAML):

```markdown
---
title: Post title
description: One-sentence summary for search results and blog list cards.
date: 2026-11-23
updated: 2026-11-24
related: other-post-slug, another-slug
---

First paragraph of the article...
```

### Fields

- `title` (required): Article title (`<title>`, `<h1>`, Open Graph, JSON-LD).
- `description` (required): Meta description and list-page summary.
- `date` (required): Publication date in `YYYY-MM-DD`.
- `updated` (optional): Last modified date in `YYYY-MM-DD`; falls back to `date`.
- `related` (optional): Comma-separated list of post `<slug>` values linked at the end of the article (links to the same language if available, otherwise `en`).

## Markdown Rules

- Rendered with `markdown-it-py` (`commonmark` preset + `table` extension).
- Raw HTML in `.md` files is disabled (`html=False`) and escaped automatically.
- Two download CTA cards are injected automatically into every article: one after the first `</p>` and one at the end of the article.

## Building & Checking

```bash
# Generate blog HTML pages and update docs/sitemap.xml
uv run python scripts/build_blog.py

# Verify generated pages and docs/sitemap.xml are up to date (used in CI)
uv run python scripts/build_blog.py --check
```
