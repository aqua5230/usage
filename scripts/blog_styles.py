# SPDX-License-Identifier: AGPL-3.0-only
"""Shared and page-specific styles for the generated blog."""

# Keep the serif family in sync with the font loaded for each language.
DISPLAY_FONTS = {
    "en": "Source+Serif+4",
    "zh-TW": "Noto+Serif+TC",
    "zh-CN": "Noto+Serif+SC",
    "ja": "Noto+Serif+JP",
    "ko": "Noto+Serif+KR",
}

COMMON_CSS = """\
:root {
  color-scheme: dark;
  --bg: #141312;
  --bg-soft: #1b1917;
  --bg-card: #1e1c1a;
  --fg: #f3ede4;
  --fg-dim: #b9b0a6;
  --fg-dimmer: #a79d92;
  --fg-footer: #a79d92;
  --accent: #ff8c42;
  --accent-soft: rgba(255, 140, 66, 0.12);
  --accent-hover: #ffa365;
  --border: rgb(255 236 214 / 11%);
  --page-width: 1128px;
  --display: "Noto Serif TC", "Songti TC", serif;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
}
:lang(en) { --display: "Source Serif 4", Georgia, serif; }
:lang(zh-CN) { --display: "Noto Serif SC", "Songti SC", serif; }
:lang(ja) { --display: "Noto Serif JP", "Hiragino Mincho ProN", serif; }
:lang(ko) { --display: "Noto Serif KR", "AppleMyungjo", serif; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html {
  scroll-behavior: smooth;
  overflow-x: clip;
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
}
body {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text",
    "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans CJK TC", "Noto Sans CJK SC",
    "Noto Sans JP", "Noto Sans KR", Arial, sans-serif;
  background: var(--bg);
  color: var(--fg);
  line-height: 1.65;
  -webkit-font-smoothing: antialiased;
  overflow-x: clip;
}
a { color: inherit; text-decoration: none; }
img { max-width: 100%; height: auto; display: block; }
::selection { background: rgba(255, 140, 66, 0.3); color: #fff; }
:where(a, button):focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
:lang(ko) :is(h1, h2, h3) { word-break: keep-all; }
:lang(ja) :is(h1, h2, h3) { word-break: auto-phrase; }
:lang(zh) :is(h1, h2, h3) { word-break: keep-all; overflow-wrap: break-word; }
/* Mirrors docs/index.html: CJK headings drop the negative tracking, and text-wrap keeps a
   single character off the last line. */
:is(:lang(zh), :lang(ja), :lang(ko)) :is(.post-header h1, .blog-hero h1, .prose h2) {
  letter-spacing: 0;
}
h1, h2, h3 { text-wrap: balance; }
.title-phrase { white-space: nowrap; }
p, li { text-wrap: pretty; }
.skip-link {
  position: absolute;
  left: -9999px;
  top: auto;
  z-index: 100;
  background: var(--bg-card);
  color: var(--fg);
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid var(--accent);
  font-size: 14px;
}
.skip-link:focus { left: 16px; top: 16px; }
.wrap { width: 100%; max-width: 820px; margin: 0 auto; padding: 0 24px; }
@media (max-width: 640px) { .wrap { padding: 0 16px; } }
.topbar {
  position: sticky;
  top: 0;
  z-index: 50;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
}
.topbar .wrap {
  max-width: 1080px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 52px;
  flex-wrap: wrap;
  padding-top: 6px;
  padding-bottom: 6px;
}
.brand {
  font-weight: 600;
  font-size: 16px;
  letter-spacing: -0.01em;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
@property --p { syntax: "<angle>"; inherits: false; initial-value: 0deg; }
.brand-dot { position: relative; width: 20px; height: 20px; flex: 0 0 20px; }
.brand-dot svg { position: absolute; inset: 0; width: 20px; height: 20px; }
.brand-ring-base { opacity: 0.3; }
.brand-ring-progress {
  --p: 226deg;
  -webkit-mask: conic-gradient(from 331deg, #000 0deg var(--p), transparent var(--p) 360deg);
  mask: conic-gradient(from 331deg, #000 0deg var(--p), transparent var(--p) 360deg);
  animation: brand-draw 0.9s ease-out;
}
.brand-cat { opacity: 1; animation: brand-cat-appear 0.35s 0.82s both; }
.brand-tail { transform-origin: 23px 51px; }
.brand-ear { transform-box: fill-box; transform-origin: center bottom; }
.brand:hover .brand-tail { animation: brand-wag 0.52s ease-in-out; }
.brand:hover .brand-ear-left { animation: brand-ears 0.22s 2 alternate; }
.brand:hover .brand-ear-right { animation: brand-ears 0.22s 0.05s 2 alternate-reverse; }
@keyframes brand-draw { from { --p: 0deg; } }
@keyframes brand-cat-appear { from { opacity: 0; } }
@keyframes brand-wag {
  30% { transform: rotate(-18deg); }
  65% { transform: rotate(13deg); }
  100% { transform: rotate(0); }
}
@keyframes brand-ears { to { transform: rotate(7deg) translateY(-1px); } }
@media (prefers-reduced-motion: reduce) {
  .brand-ring-progress, .brand-cat,
  .brand:hover .brand-tail, .brand:hover .brand-ear { animation: none; }
}
.top-nav {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 14.5px;
  color: var(--fg-dim);
  flex-wrap: wrap;
}
.top-nav a:hover, .top-nav a[aria-current="page"] { color: var(--fg); }
.lang-links {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.lang-links a {
  font-size: 12.5px;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--border);
  color: var(--fg-dim);
  background: rgba(255, 255, 255, 0.02);
}
.lang-links a:hover { color: var(--fg); border-color: var(--fg-dimmer); }
.lang-links a[aria-current="page"] {
  color: var(--accent);
  border-color: rgba(255, 140, 66, 0.45);
  background: var(--accent-soft);
  font-weight: 600;
}
main { flex: 1 0 auto; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
"""


ARTICLE_CSS = """\
.embed { display: block; }
.embed iframe {
  display: block; width: 100%; aspect-ratio: 16 / 10;
  border: 0; border-radius: 10px; background: #000;
}
.embed a { display: inline-block; margin-top: 6px; font-size: 14px; color: var(--accent); }
main { padding: 48px 0 72px; }
@media (max-width: 640px) { main { padding: 32px 0 56px; } }
.post-meta time { font-family: var(--mono); }
.post-meta {
  font-size: 13px;
  color: var(--fg-dimmer);
  margin-bottom: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
}
.post-header h1, .prose :is(h2, h3) {
  color: var(--fg);
  font-family: var(--display);
  font-weight: 600;
}
.post-header h1 {
  font-size: clamp(28px, 4vw, 40px);
  line-height: 1.2;
  letter-spacing: -0.025em;
  margin-bottom: 14px;
  overflow-wrap: anywhere;
}
.prose { font-size: 16.5px; line-height: 1.75; color: var(--fg-dim); }
.prose > * + * { margin-top: 1.15em; }
.prose h2 {
  font-size: clamp(22px, 2.6vw, 27px);
  line-height: 1.3;
  margin-top: 2em;
  margin-bottom: 0.6em;
  letter-spacing: -0.02em;
}
.prose h3 { font-size: 19px; line-height: 1.35; margin-top: 1.6em; margin-bottom: 0.5em; }
.prose p, .prose li { overflow-wrap: anywhere; }
.prose ul, .prose ol { padding-left: 1.4em; }
.prose li + li { margin-top: 0.35em; }
.prose a { color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }
.prose a:hover { color: var(--accent-hover); }
.prose blockquote {
  padding: 12px 16px;
  border: 1px solid var(--border);
  background: var(--bg-soft);
  border-radius: 8px;
  color: var(--fg-dim);
}
.prose :not(pre) > code {
  font-family: var(--mono);
  font-size: 0.88em;
  background: rgba(255, 255, 255, 0.07);
  padding: 2px 6px;
  border-radius: 4px;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.prose pre {
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  overflow-x: auto;
  max-width: 100%;
  font-family: var(--mono);
  font-size: 13.5px;
  line-height: 1.5;
}
.prose pre code { background: none; padding: 0; font-size: inherit; }
.prose pre code.language-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.prose table {
  display: block;
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
  font-size: 14.5px;
}
.prose th, .prose td {
  border: 1px solid var(--border);
  padding: 8px 12px;
  text-align: left;
}
.prose th { background: var(--bg-soft); font-weight: 600; }
.prose hr { border: 0; border-top: 1px solid var(--border); margin: 2em 0; }
.blog-cta-card {
  margin: 28px 0;
  padding: 22px 24px;
  border-radius: 14px;
  border: 1px solid rgba(255, 140, 66, 0.28);
  background: var(--bg-card);
}
.blog-cta-card h2 {
  font-size: 18px;
  line-height: 1.35;
  margin: 0 0 8px;
  color: var(--fg);
}
.blog-cta-card p {
  font-size: 14.5px;
  line-height: 1.6;
  color: var(--fg-dim);
  margin: 0 0 16px;
}
.blog-cta-actions { display: flex; flex-wrap: wrap; gap: 10px; }
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 40px;
  padding: 0 15px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  border: 1px solid transparent;
  text-decoration: none !important;
  transition: background 150ms ease, border-color 150ms ease;
}
.btn-primary { background: var(--accent); color: var(--bg) !important; }
.btn-primary:hover { background: var(--accent-hover); }
.btn-secondary {
  background: rgba(255, 255, 255, 0.04);
  color: var(--fg) !important;
  border-color: rgba(255, 255, 255, 0.14);
}
.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.09);
  border-color: rgba(255, 255, 255, 0.25);
}
.related-section {
  margin-top: 40px;
  padding-top: 28px;
  border-top: 1px solid var(--border);
}
.related-section h2 { font-size: 20px; margin-bottom: 14px; }
.related-list { list-style: none; display: grid; gap: 10px; }
.related-list a {
  display: grid;
  gap: 4px;
  overflow-wrap: anywhere;
}
.related-section .related-list a {
  padding: 14px 16px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  transition: border-color 140ms ease;
}
.related-section .related-list a:is(:hover, :focus-visible) { border-color: var(--accent); }
.related-list a:is(:hover, :focus-visible) .related-title { color: var(--accent); }
.related-title { font-size: 16px; font-weight: 600; line-height: 1.4; }
.related-desc { font-size: 14.5px; line-height: 1.55; color: var(--fg-dim); }
.prose h2[id] { scroll-margin-top: 84px; }
.wrap-article { max-width: 800px; }
.article-main { min-width: 0; }
.left-rail, .right-rail, .news-rail { display: none; }
.post-header { margin-bottom: 28px; padding-bottom: 24px; border-bottom: 1px solid var(--border); }
.post-header h1 { margin-bottom: 20px; }
.breadcrumb { color: var(--fg-dim); font-size: 14px; margin-bottom: 16px; overflow-wrap: anywhere; }
.breadcrumb a:hover { color: var(--fg); text-decoration: underline; }
.breadcrumb span[aria-hidden] { margin-inline: 0.45em; color: var(--fg-dimmer); }
.post-header .post-meta { align-items: center; justify-content: space-between; margin-bottom: 0; }
.mobile-menu { margin-bottom: 28px; }
.categories, .mobile-menu { border-top: 1px solid var(--border); }
.mobile-menu .categories { border-top: 0; }
.category, .mobile-menu { border-bottom: 1px solid var(--border); }
.mobile-menu .category:last-child { border-bottom: 0; }
.category > summary, .mobile-menu > summary {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 43px;
  list-style: none;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}
.category > summary::-webkit-details-marker, .mobile-menu > summary::-webkit-details-marker {
  display: none;
}
.category > summary::after, .mobile-menu > summary::after {
  content: "";
  width: 6px;
  height: 6px;
  flex-shrink: 0;
  border-right: 1px solid currentColor;
  border-bottom: 1px solid currentColor;
  transform: rotate(-45deg);
  margin-inline: auto 5px;
  color: var(--fg-dim);
}
.category[open] > summary::after, .mobile-menu[open] > summary::after { transform: rotate(45deg); }
.category > summary:hover, .mobile-menu > summary:hover { color: var(--fg-dim); }
.article-layout summary:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.category > summary svg { width: 18px; height: 18px; flex: 0 0 18px; color: var(--fg-dim); }
.category-articles { list-style: none; padding: 0 0 10px 28px; }
.category-articles a {
  display: block;
  font-size: 14px;
  line-height: 1.55;
  color: var(--fg-dim);
  padding: 5px 0;
  overflow-wrap: anywhere;
}
.category-articles a:hover, .category-articles a[aria-current="page"] { color: var(--fg); }
.category-articles a[aria-current="page"] { font-weight: 650; }
.toc-mobile {
  padding: 14px 0;
  border-top: 1px solid var(--border);
}
.toc-mobile summary {
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  color: var(--fg);
  list-style: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.toc-mobile summary::-webkit-details-marker { display: none; }
.toc-mobile summary::after {
  content: "▾";
  font-size: 12px;
  color: var(--fg-dimmer);
  transition: transform 150ms ease;
}
.toc-mobile[open] summary::after { transform: rotate(180deg); }
.toc-mobile .toc-list {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
.toc-title {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--fg-dimmer);
  margin-bottom: 10px;
}
.toc-list { list-style: none; display: grid; gap: 8px; }
.toc-list a {
  display: block;
  font-size: 13px;
  line-height: 1.45;
  color: var(--fg-dim);
  padding: 2px 0;
  transition: color 140ms ease;
  overflow-wrap: anywhere;
}
.toc-list a:hover { color: var(--fg); }
.toc-list a[aria-current="location"] { color: var(--fg); font-weight: 600; }
.page-toc .toc-list { border-inline-start: 1px solid var(--border); }
.page-toc .toc-list a {
  border-inline-start: 1px solid transparent;
  margin-inline-start: -1px;
  padding-inline-start: 12px;
}
.page-toc .toc-list a[aria-current="location"] { border-inline-start-color: var(--fg); }
.page-toc + .news-rail:not([hidden]) {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}
.news-title {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--fg-dimmer);
  margin-bottom: 4px;
}
.news-list { display: grid; }
.news-item {
  display: block;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}
.news-item:hover .news-item-name { color: var(--accent); }
.news-item-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.news-item-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--fg);
  transition: color 140ms ease;
}
.news-item-date {
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--fg-dimmer);
  white-space: nowrap;
}
.news-item-title {
  font-size: 13px;
  line-height: 1.45;
  color: var(--fg-dim);
  overflow-wrap: anywhere;
}
.news-all {
  display: inline-block;
  margin-top: 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
}
.news-all:hover { color: var(--accent-hover); }
@media (min-width: 1025px) {
  .wrap-article { max-width: 1360px; }
  .article-layout {
    display: grid;
    grid-template-columns: clamp(185px, 17vw, 222px) minmax(0, 1fr) clamp(180px, 17vw, 222px);
    align-items: start;
    gap: clamp(24px, 3.25vw, 48px);
  }
  .left-rail, .right-rail {
    display: block;
    position: sticky;
    top: 84px;
    max-height: calc(100vh - 108px);
    overflow-y: auto;
    scrollbar-width: thin;
    padding: 4px;
    margin: -4px;
  }
  .mobile-menu { display: none; }
}
@media (min-width: 1440px) {
  .news-rail:not([hidden]) { display: block; }
}
"""


LIST_CSS = """\
/* Editorial layout · usage orange · category cards above a chronological article grid.
   Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V4 */
:root {
  --card-art: #1b1918;
  --badge: #d1bca2;
  --rust: #4a2a25;
  --deep-blue: #20334b;
  --indigo: #342d46;
  --deep-green: #28362b;
  --art-shadow: rgb(0 0 0 / 24%);
  --octagon: polygon(30% 0, 70% 0, 100% 30%, 100% 70%, 70% 100%, 30% 100%, 0 70%, 0 30%);
  --contours: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 \
520 248'%3E%3Cg fill='none' stroke='%23e9dfd2' stroke-opacity='.05' stroke-width='1'%3E%3Cpath\
 d='M-45 55C20 13 61 17 116 56s87 24 130-17 107-59 166-30 84 24 137-10M-45 75C23 32 57 36 110 \
73s92 31 149-21 107-58 159-28 82 18 128-11M-45 97C22 55 54 55 105 91s108 29 166-21 102-54 \
153-26 83 15 126-14M-45 121C21 77 53 72 102 110s113 34 178-17 105-59 151-27 79 9 116-17M-45 \
146C21 102 51 89 98 128s122 37 192-16 101-51 145-24 78 5 112-22M-45 172C26 125 52 109 94 \
147s134 40 203-15 100-49 142-25 73 1 110-27M-45 199C25 153 52 133 91 167s143 40 213-13 99-48 \
138-27 77-2 107-30M-45 230C21 184 53 157 91 189s147 44 222-10 95-48 132-30 70-4 106-35M-45 \
261C28 216 53 180 98 213s156 32 224-12 90-46 129-32 67-10 102-42M-12 264C35 233 64 207 101 \
235s139 32 220-12 99-46 133-35 69-10 99-46M182 260C242 270 291 260 340 235s88-37 119-30 61-15 \
89-44'/%3E%3C/g%3E%3C/svg%3E");
}
main { padding-bottom: 94px; }
.blog-page { max-width: var(--page-width); }
.blog-page [id], main { scroll-margin-top: 90px; }
.blog-hero {
  position: relative;
  isolation: isolate;
  text-align: center;
  padding: 81px 0 31px;
}
.blog-hero h1, .section-head h2 { font-family: var(--display); font-weight: 600; }
.blog-hero h1 { font-size: clamp(42px, 5vw, 72px); line-height: 1.16; }
.blog-hero p {
  max-width: 38em;
  margin: 14px auto 0;
  color: var(--fg-dim);
  font-size: 17px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px 28px;
  margin-bottom: 14px;
}
.section-head h2 {
  font-size: clamp(25px, 3vw, 34px);
  line-height: 1.25;
  overflow-wrap: anywhere;
}
.section-head p { color: var(--fg-dim); font-size: 15px; margin-top: 6px; }
.section-link {
  display: inline-flex;
  gap: 9px;
  align-items: center;
  width: fit-content;
  color: var(--accent);
  font-size: 14px;
  white-space: nowrap;
}
.section-link:hover { text-decoration: underline; text-underline-offset: 4px; }
.category-grid, .post-list {
  display: grid;
  gap: 20px;
}
.category-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.post-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.category-tile, .post-card {
  min-width: 0;
  display: grid;
  grid-template-rows: auto 1fr;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--bg-card);
}
.category-tile:hover, .post-card:hover, .post-card:target { border-color: var(--accent); }
.category-art {
  display: grid;
  place-items: center;
  height: 126px;
  border-radius: 15px 15px 0 0;
  background: var(--category-color);
}
.category-getting-started { --category-color: var(--deep-green); }
.category-claude-code { --category-color: var(--rust); }
.category-codex { --category-color: var(--indigo); }
.category-antigravity { --category-color: var(--deep-blue); }
.category-badge {
  display: grid;
  place-items: center;
  width: 84px;
  aspect-ratio: 1;
  color: var(--bg);
  background: var(--badge);
  clip-path: var(--octagon);
}
.category-logo {
  display: block;
  width: 60%;
  height: auto;
  aspect-ratio: 1;
  object-fit: contain;
}
.category-copy {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-rows: auto 1fr auto;
  gap: 4px 8px;
  padding: 13px 16px 12px;
}
.category-name { grid-column: 1 / -1; font-size: 20px; line-height: 1.25; font-weight: 650; }
.category-copy p { grid-column: 1 / -1; color: var(--fg-dim); font-size: 14px; line-height: 1.5; }
.category-latest {
  min-width: 0;
  overflow: hidden;
  color: var(--fg-dimmer);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.category-count {
  grid-area: 3 / 2;
  align-self: baseline;
  color: var(--fg-dimmer);
  font-size: 13px;
  white-space: nowrap;
}
@media (min-width: 960px) {
  .category-grid { max-width: 1000px; margin-inline: auto; padding: 5px 14px 10px; }
  .category-tile { transition: transform 180ms ease, border-color 180ms ease; }
  .category-tile:first-child { transform: translateY(10px) rotate(-3.5deg); }
  .category-tile:last-child { transform: translateY(10px) rotate(3.5deg); }
  .category-tile:is(:hover, :focus-visible) { transform: translateY(-6px); }
}
@media (prefers-reduced-motion: reduce) {
  .category-tile { transition: none; }
}
.articles { position: relative; margin-top: 29px; }
.article-filter-target { position: absolute; inset-block-start: 0; }
.article-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.article-filters a {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--fg-dim);
  font-size: 13px;
  white-space: nowrap;
}
.article-filters a:hover { border-color: var(--fg-dimmer); }
.articles:not(:has(.article-filter-target:target)) .article-filters [href="#all"],
.articles:has(#getting-started:target) .article-filters [href="#getting-started"],
.articles:has(#claude-code:target) .article-filters [href="#claude-code"],
.articles:has(#codex:target) .article-filters [href="#codex"],
.articles:has(#antigravity:target) .article-filters [href="#antigravity"] {
  color: var(--accent);
  border-color: var(--accent);
}
.articles:has(#getting-started:target) .post-card:not([data-category="getting-started"]),
.articles:has(#claude-code:target) .post-card:not([data-category="claude-code"]),
.articles:has(#codex:target) .post-card:not([data-category="codex"]),
.articles:has(#antigravity:target) .post-card:not([data-category="antigravity"]) {
  display: none;
}
.post-art {
  display: grid;
  place-items: center;
  height: 152px;
  padding: 16px 13%;
  border-radius: 15px 15px 0 0;
  border-bottom: 1px solid var(--border);
  background: var(--card-art) var(--contours) center / cover no-repeat;
}
.post-card:nth-child(even) .post-art { background-size: 124% auto; background-position: right 60%; }
.post-cover {
  width: auto;
  height: auto;
  max-width: 100%;
  max-height: 119px;
  border-radius: 6px;
  object-fit: contain;
  box-shadow: 0 4px 12px var(--art-shadow);
}
.post-copy { display: flex; flex-direction: column; min-width: 0; padding: 17px 20px 18px; }
.post-title { font-size: clamp(19px, 1.9vw, 24px); line-height: 1.4; text-wrap: pretty; }
:lang(zh) .post-title { word-break: normal; overflow-wrap: anywhere; }
.post-card:hover .post-title { color: var(--accent); }
.post-summary {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  overflow-wrap: anywhere;
  text-wrap: wrap;
  color: var(--fg-dim);
  font-size: 15px;
  line-height: 1.55;
  margin: 6px 0 0;
}
.post-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 6px;
  color: var(--fg-dimmer);
  font-size: 13px;
  margin-top: auto;
  padding-top: 14px;
}
.post-meta time { font-family: var(--mono); }
.post-meta span { white-space: nowrap; }
@media (max-width: 760px) {
  .category-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .post-art { height: 120px; padding: 13px 10%; }
  .post-cover { max-height: 93px; }
}
@media (max-width: 640px) {
  main { padding-bottom: 54px; }
  .blog-hero { padding: 30px 0 44px; }
  .blog-hero h1 { overflow-wrap: anywhere; }
  .blog-hero p { max-width: 22em; font-size: 15px; }
  .section-head { display: grid; gap: 8px; margin-bottom: 16px; }
  .category-grid, .post-list { gap: 12px; }
  .post-list { grid-template-columns: minmax(0, 1fr); }
  .category-art { height: 96px; }
  .category-badge { width: 65px; }
  .category-copy {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto 1fr auto auto;
    padding: 11px 12px;
  }
  .category-name { font-size: 17px; }
  .category-count { grid-area: 4 / 1; }
  .category-latest {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .post-art { height: 158px; padding: 13px 8%; }
  .post-cover { max-height: 132px; }
  .articles { margin-top: 44px; }
  .article-filters { gap: 4px; }
  .article-filters a { padding-inline: 6px; }
  .post-copy { padding: 13px 15px 15px; }
  .post-title { text-wrap: balance; }
  .post-meta { gap: 0 4px; font-size: 12px; }
  .blog-page [id], main { scroll-margin-top: 112px; }
}
@media (max-width: 430px) {
  .topbar .wrap { gap: 5px 10px; }
  .top-nav { order: 1; width: 100%; justify-content: space-between; }
  .topbar .lang-links { max-width: 72%; justify-content: flex-end; }
}
.hero-badges {
  position: absolute;
  z-index: -1;
  inset: 0;
  pointer-events: none;
}
.hero-badges::before {
  content: "";
  position: absolute;
  inset: 34px 0 auto;
  width: 760px;
  max-width: 100%;
  height: 128px;
  margin-inline: auto;
  border: 1px solid rgb(255 236 214 / 12%);
  border-bottom: 0;
  border-radius: 50% 50% 0 0 / 100% 100% 0 0;
  mask-image: linear-gradient(to right, transparent, #000 12%, #000 88%, transparent);
}
.hero-badges .category-badge {
  position: absolute;
  top: var(--badge-top);
  left: calc(50% + var(--badge-offset));
  width: 56px;
  color: var(--fg);
  background: #322b25;
  transform: translate(-50%, -50%) rotate(var(--badge-angle));
}
.hero-badges .category-logo { width: 72%; opacity: 0.82; }
.hero-badges .category-badge:nth-child(1) {
  --badge-top: 86px;
  --badge-offset: -306px;
  --badge-angle: -6deg;
}
.hero-badges .category-badge:nth-child(2) {
  --badge-top: 55px;
  --badge-offset: -208px;
  --badge-angle: -3deg;
}
.hero-badges .category-badge:nth-child(3) {
  --badge-top: 55px;
  --badge-offset: 208px;
  --badge-angle: 3deg;
}
.hero-badges .category-badge:nth-child(4) {
  --badge-top: 86px;
  --badge-offset: 306px;
  --badge-angle: 6deg;
}
@media (max-width: 820px) {
  .hero-badges {
    position: static;
    display: flex;
    justify-content: center;
    gap: 12px;
    margin-bottom: 14px;
  }
  .hero-badges::before { display: none; }
  .hero-badges .category-badge {
    position: static;
    width: 40px;
    transform: rotate(var(--badge-angle));
  }
}
"""


FOOTER_CSS = """\
/* Hallmark · footer · editorial · existing C2 palette */
.site-footer > .wrap { max-width: var(--page-width); }
.site-footer { border-top: 1px solid var(--border); background: var(--bg-soft); }
.footer-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 0.85fr) minmax(0, 1.25fr) minmax(0, 0.75fr);
  gap: 28px;
  padding: 36px 0 32px;
}
.footer-brand .brand { gap: 8px; font-size: 20px; }
.footer-brand .brand-dot { width: 32px; height: 32px; flex-basis: 32px; }
.footer-brand .brand-dot svg { width: 32px; height: 32px; animation: none; }
.footer-brand h2 {
  margin: 10px 0 6px;
  font-size: 16px;
  text-wrap: wrap;
  word-break: normal;
}
.footer-brand p {
  color: var(--fg-dim);
  font-size: 14px;
  line-height: 1.75;
}
.footer-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.footer-actions a {
  padding: 6px 12px;
  border: 1px solid var(--fg-dimmer);
  border-radius: 6px;
  color: var(--fg-dim);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}
.footer-actions a:hover { color: var(--fg); border-color: var(--fg); }
.footer-actions .footer-install { color: var(--accent); border-color: var(--accent); }
.footer-actions .footer-install:hover {
  color: var(--accent-hover);
  background: var(--accent-soft);
}
.footer-links h2 {
  padding-top: 7px;
  margin-bottom: 6px;
  color: var(--fg-footer);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
}
.footer-links ul { list-style: none; }
.footer-links a {
  display: flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  max-width: 100%;
  padding: 5px 0;
  color: var(--fg-dim);
  font-size: 14px;
  white-space: nowrap;
}
.footer-links a:hover { color: var(--fg); }
.footer-links a :is(img, svg) { width: 16px; height: 16px; flex: 0 0 16px; object-fit: contain; }
.footer-latest a { display: block; overflow: hidden; text-overflow: ellipsis; }
.footer-bottom {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 24px;
  border-top: 1px solid var(--border);
  padding: 16px 0 20px;
}
.footer-credit { flex: 1 1 200px; color: var(--fg-footer); font-size: 13px; }
.footer-bottom .lang-links { margin-inline-start: auto; }
.footer-credit a { color: var(--fg-dim); text-decoration: underline; text-underline-offset: 3px; }
.footer-credit a:hover { color: var(--fg); }
@media (max-width: 900px) {
  .footer-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; }
  .footer-brand { grid-column: 1 / -1; max-width: 420px; }
}
@media (max-width: 520px) {
  .footer-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    grid-template-areas: "brand brand" "categories usage" "latest latest";
    reading-flow: grid-rows;
    gap: 18px;
    padding: 27px 0 22px;
  }
  .footer-brand { grid-area: brand; }
  .footer-categories { grid-area: categories; }
  .footer-latest { grid-area: latest; }
  .footer-usage { grid-area: usage; }
  .footer-links h2 { padding-top: 0; }
}
"""
