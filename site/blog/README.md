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
tool: claude-code
related: other-post-slug, another-slug
image: cover.png
---

First paragraph of the article...
```

### Fields

- `title` (required): Article title (`<title>`, `<h1>`, Open Graph, JSON-LD).
- `description` (required): Meta description and list-page summary.
- `date` (required): Publication date in `YYYY-MM-DD`.
- `updated` (optional): Last modified date in `YYYY-MM-DD`; falls back to `date`.
- `tool` (required for new posts): The tool the post is about, for future category filters. One of `claude-code`, `codex`, `antigravity`, `grok`, `muse`, or `general` (tool roundups and posts that cover several tools). Use the same value in every language of a post. The blog index shows it as a label next to the date; `general` shows no label.
- `related` (optional): Comma-separated list of post `<slug>` values linked at the end of the article (links to the same language if available, otherwise `en`).
- `image` (optional): Filename of an image in the same `<slug>` directory to use for `og:image`, `twitter:image`, and JSON-LD `image` (omitting `og:image:width` and `og:image:height`). Defaults to the site-wide OG image.

## Markdown Rules

- Rendered with `markdown-it-py` (`commonmark` preset + `table` extension).
- Raw HTML in `.md` files is disabled (`html=False`) and escaped automatically.
- Two download CTA cards are injected automatically into every article: one after the first `</p>` and one at the end of the article.

## Images

- Place image files directly inside the post directory (`site/blog/<slug>/<filename>`). Supported extensions (case-insensitive): `.jpg`, `.jpeg`, `.png`, `.webp`, `.svg`. Other files are ignored.
- Each image is copied once to `docs/blog/<slug>/<filename>`, regardless of which languages exist. Do not duplicate images per language.
- Reference local images in Markdown by bare filename only: `![alt text](diagram.png)`. Non-English pages automatically rewrite `<img src="...">` to `../../../blog/<slug>/<filename>`; `http://`, `https://`, and `/` URLs are left untouched.
- Use the optional `image: <filename>` frontmatter field to override `og:image`, `twitter:image`, and JSON-LD `image` with the post's own image URL (without `og:image:width` / `og:image:height`).
- Referencing a missing filename in Markdown or in `image:` fails the build with a `ValueError`.

## Building & Checking

```bash
# Generate blog HTML pages and update docs/sitemap.xml
uv run python scripts/build_blog.py

# Verify generated pages and docs/sitemap.xml are up to date (used in CI)
uv run python scripts/build_blog.py --check
```

## Writing Style

Every post is checked against these rules before it ships. They come from research on why AI-written prose is hard to read: readers predict the next word and hold the subject in memory until the verb arrives, and AI text breaks both.

- **Things don't act like people.** Write "Codex reports the reset time", not "the status line spits out the reset time" or "the reset gives you a gift". In Chinese, avoid verbs such as 吐、吃、燒光 for software or quotas.
- **Keep the subject next to its verb.** Split long modifiers into their own sentence. One sentence carries one idea.
- **Keep the connecting words.** Don't drop "that", "because", "so" (中文的「因為、所以、但是」) to save space; the reader guesses wrong without them, and a missing link can turn a fact into a false one.
- **Use the words people expect.** Common collocations over clever ones. No slang such as 滿血復活、白拿.
- **One name per thing.** Pick a term (for example 週期 for a weekly period) and use it everywhere. Taiwan Chinese, not mainland terms (窗口、視頻).
- **Don't repeat a fact** in the intro, the bullets, every section, and the takeaways. Say it where it belongs.
- **Chinese bold leads end outside the bold.** Write `**…時刻**。它不是`, with no space after `。`. A space after full-width punctuation shows as a gap, and `。**它` breaks the Markdown bold.
- **Every number has a source** in the post's fact sheet: an official page quoted word for word, or first-hand data the author provided.
