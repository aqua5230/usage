#!/usr/bin/env python3
"""產生官網面板展示用的 HTML，餵一份寫死的假資料。

清單走 panels.all_panels()，新增面板會自己出現在官網上，不必改這支腳本。
不讀任何真實用量檔，不會把使用者的專案名稱或數字寫進產物。
用法：.venv/bin/python scripts/make_panel_demo.py [輸出目錄] [預設語言]
預設輸出到 docs/panels/。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from i18n import _t  # noqa: E402
from menubar import app as menubar  # noqa: E402
from menubar.state import PopoverState, QuotaRowState, format_human_time  # noqa: E402
from panels import all_panels  # noqa: E402
from panels.dynamic_height import inject_content_height_script  # noqa: E402
from panels.payload import _load_panel_html, _state_payload  # noqa: E402

# 面板用 window.webkit.messageHandlers 把量到的自然高度回報給原生端。
# 瀏覽器裡沒有那座橋，補一個假的，把高度轉發給外層的展示頁。
WEBKIT_SHIM = """
<script>
window.webkit = { messageHandlers: { usage: { postMessage: function(raw) {
  try {
    var message = JSON.parse(raw);
    if (message.action === "content_height") {
      parent.postMessage({ usagePanelHeight: message.height }, "*");
    }
  } catch (error) {}
} } } };
</script>
"""

# talent_market 是功能面板不是佈景主題，官網那句 "Thirteen built-in themes"
# 數的就是排除它之後的 13 個。清單走 all_panels()，新增面板會自己出現。
NOT_A_THEME = frozenset({"talent_market"})

DEMO_PROJECTS = [
    ("aurora-api", 4_820_000, 12.40),
    ("mobile-client", 3_115_000, 8.05),
    ("data-pipeline", 1_940_000, 4.92),
    ("docs-site", 860_000, 2.11),
    ("infra-scripts", 415_000, 1.03),
]


def _row(language: str, title_key: str, percent: float, reset_seconds: float) -> QuotaRowState:
    # 每個字串都走 _t，跟 app 產生的一模一樣；自己編會跟真實排版對不上。
    # color 只給原生 UI 用，_row_payload 不會把它輸出到網頁 payload。
    return QuotaRowState(
        title=_t(language, title_key),
        percent=percent,
        percent_text=_t(language, "percent_used", value=f"{percent:g}"),
        reset_text=_t(language, "reset_in", time=format_human_time(reset_seconds, language)),
        color=(0.36, 0.78, 0.45),
        warning=percent >= 80,
        available=True,
    )


def _demo_state(language: str) -> PopoverState:
    state = menubar._empty_state(language)
    state.claude_session = _row(language, "session_label", 62.0, 8_040)
    state.claude_weekly = _row(language, "weekly_label", 38.0, 280_800)
    state.codex_session = _row(language, "session_label", 45.0, 6_480)
    state.codex_weekly = _row(language, "weekly_label", 27.0, 352_800)
    state.agy_session = _row(language, "session_label", 18.0, 12_600)
    state.agy_weekly = _row(language, "weekly_label", 12.0, 464_400)
    state.agy_group_name = "GEMINI MODELS"
    state.hide_agy = False
    state.projects = list(DEMO_PROJECTS)
    state.projects_yesterday = list(DEMO_PROJECTS)
    state.projects_7d = list(DEMO_PROJECTS)
    state.projects_30d = list(DEMO_PROJECTS)
    state.projects_all = list(DEMO_PROJECTS)
    state.rate_text = _t(language, "rate_text", value=_t(language, "group_active"))
    state.status_text = _t(language, "status_text", value=_t(language, "status_synced"))
    # 模板自己帶錢字號，cost 只給數字，否則會印成 $$28.51。
    state.today_text = _t(language, "today_text", cost="28.51", tokens="11,150,000")
    state.yesterday_text = _t(language, "yesterday_text", cost="19.84", tokens="7,420,000")
    state.show_install_button = False
    return state


LANGUAGES = ["en", "zh-TW", "zh-CN", "ja", "ko"]


def main() -> int:
    out_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else _REPO_ROOT / "docs" / "panels"
    default_language = sys.argv[2] if len(sys.argv) > 2 else "en"
    out_dir.mkdir(parents=True, exist_ok=True)

    # usageSetLanguage 只換靜態標籤；Session / Rate: Active 這些字串是 Python
    # 產生的，換語言換不掉，所以每種語言各存一份 payload 讓展示頁自己挑。
    payloads = {lang: _state_payload(_demo_state(lang)) for lang in LANGUAGES}
    encoded = json.dumps(payloads, ensure_ascii=False)
    injection = (
        "<script>"
        f"window.usageDemoPayloads={encoded};"
        f"window.usageDemoLanguage={json.dumps(default_language)};"
        "window.usageDemoSetLanguage=function(language){"
        "  var payload=window.usageDemoPayloads[language];"
        "  if(!payload)return;"
        "  window.usageDemoLanguage=language;"
        "  if(typeof window.usageSetLanguage==='function')window.usageSetLanguage(language);"
        "  window.usageApplyState(payload);"
        "};"
        "window.addEventListener('message',function(event){"
        "  var language=event.data&&event.data.usageDemoLanguage;"
        "  if(language)window.usageDemoSetLanguage(language);"
        "});"
        "document.addEventListener('DOMContentLoaded',function(){"
        "  window.usageDemoSetLanguage(window.usageDemoLanguage);"
        "});"
        "</script>"
    )

    themes = [panel for panel in all_panels() if panel.id not in NOT_A_THEME]
    index = []
    for panel in themes:
        # Panel 這個 Protocol 只宣告 id / i18n_key / preferred_size()，
        # html_filename 與 width/height 是 HTMLPanel 的實作細節，別直接取。
        width, height = panel.preferred_size()
        html = _load_panel_html(f"{panel.id}.html")
        # 順序有意義：先補假橋接，再讓 dynamic_height 包住 usageApplyState，
        # 最後才餵資料，這樣量高度的包裝已經就位。
        html = html.replace("</body>", f"{WEBKIT_SHIM}</body>", 1)
        html = inject_content_height_script(html)
        html = html.replace("</body>", f"{injection}</body>", 1)
        target = out_dir / f"{panel.id}.html"
        target.write_text(html, encoding="utf-8")
        index.append(
            {
                "id": panel.id,
                "width": width,
                "height": height,
                "names": {lang: _t(lang, panel.i18n_key) for lang in LANGUAGES},
            }
        )
        print(f"{panel.id}: {target.stat().st_size // 1024}KB")

    (out_dir / "panels.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"panels.json: {len(index)} themes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
