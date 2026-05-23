from __future__ import annotations

import html
import os
import webbrowser
from datetime import date, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Mapping


SUPPORTED_REPORT_LANGS = {"zh-TW", "zh-CN", "en", "ja", "ko"}

REPORT_TRANSLATIONS: dict[str, dict[str, str]] = {
    "zh-TW": {
        "active_days": "活躍天數",
        "cost": "花費",
        "duration": "時長",
        "empty_models": "這段期間還沒有模型用量",
        "empty_projects": "這段期間還沒有專案用量",
        "empty_daily": "這段期間還沒有每日用量",
        "empty_sessions": "這段期間還沒有可列出的會話",
        "footer": "token-tracker · 本機分析 · 資料不離本機",
        "generated": "產生時間",
        "kpi_active": "活躍日",
        "kpi_cost": "燒掉成本",
        "kpi_messages": "訊息",
        "kpi_sessions": "會話",
        "kpi_tokens": "燒掉 Tokens",
        "messages": "訊息",
        "model": "模型",
        "model_section": "最常合作的模型",
        "narrative": "你這段時間燒了 {tokens} tokens，跨足 {projects} 個專案，高峰在 {peak_date}（{peak_tokens}/天），最常合作的是 {top_model}。",
        "period": "區間",
        "project": "專案",
        "project_section": "專案熱區",
        "rank": "排名",
        "session_section": "最燒的 5 段會話",
        "sessions": "會話",
        "share": "占比",
        "start_time": "開始時間",
        "title": "你的 AI 用量回顧",
        "tokens": "Tokens",
        "trend_compare_down": "本週比上週少 {pct}%。",
        "trend_compare_first": "這是本期第一週的數據。",
        "trend_compare_flat": "本週跟上週差不多。",
        "trend_compare_new": "本週是新出現的用量。",
        "trend_compare_up": "本週是上週的 {ratio} 倍。",
        "trend_marker_new": "new",
        "trend_section": "每週燃燒趶勢",
        "unknown": "未知",
        "version": "版本",
    },
    "zh-CN": {
        "active_days": "活跃天数",
        "cost": "花费",
        "duration": "时长",
        "empty_models": "这段期间还没有模型用量",
        "empty_projects": "这段期间还没有项目用量",
        "empty_daily": "这段期间还没有每日用量",
        "empty_sessions": "这段期间还没有可列出的会话",
        "footer": "token-tracker · 本机分析 · 数据不离本机",
        "generated": "生成时间",
        "kpi_active": "活跃日",
        "kpi_cost": "烧掉成本",
        "kpi_messages": "消息",
        "kpi_sessions": "会话",
        "kpi_tokens": "烧掉 Tokens",
        "messages": "消息",
        "model": "模型",
        "model_section": "最常合作的模型",
        "narrative": "你这段时间烧了 {tokens} tokens，跨足 {projects} 个项目，高峰在 {peak_date}（{peak_tokens}/天），最常合作的是 {top_model}。",
        "period": "区间",
        "project": "项目",
        "project_section": "项目热区",
        "rank": "排名",
        "session_section": "最烧的 5 段会话",
        "sessions": "会话",
        "share": "占比",
        "start_time": "开始时间",
        "title": "你的 AI 用量回顾",
        "tokens": "Tokens",
        "trend_compare_down": "本周比上周少 {pct}%。",
        "trend_compare_first": "这是本期第一周的数据。",
        "trend_compare_flat": "本周跟上周差不多。",
        "trend_compare_new": "本周是新出现的用量。",
        "trend_compare_up": "本周是上周的 {ratio} 倍。",
        "trend_marker_new": "new",
        "trend_section": "每周燃烧趋势",
        "unknown": "未知",
        "version": "版本",
    },
    "en": {
        "active_days": "Active days",
        "cost": "Cost",
        "duration": "Duration",
        "empty_models": "No model usage in this period",
        "empty_projects": "No project usage in this period",
        "empty_daily": "No daily usage in this period",
        "empty_sessions": "No sessions to list in this period",
        "footer": "token-tracker · Local-first analytics · Data stays on device",
        "generated": "Generated",
        "kpi_active": "Active Days",
        "kpi_cost": "Burned Cost",
        "kpi_messages": "Messages",
        "kpi_sessions": "Sessions",
        "kpi_tokens": "Burned Tokens",
        "messages": "Messages",
        "model": "Model",
        "model_section": "Most-used models",
        "narrative": "You burned {tokens} tokens across {projects} projects, peaked on {peak_date} ({peak_tokens}/day), and teamed up most with {top_model}.",
        "period": "Period",
        "project": "Project",
        "project_section": "Project hot zones",
        "rank": "Rank",
        "session_section": "Top 5 burn sessions",
        "sessions": "Sessions",
        "share": "Share",
        "start_time": "Start time",
        "title": "Your AI Usage Recap",
        "tokens": "Tokens",
        "trend_compare_down": "This week dropped {pct}% vs last week.",
        "trend_compare_first": "First week of this period.",
        "trend_compare_flat": "Roughly flat vs last week.",
        "trend_compare_new": "This week has new usage vs last week.",
        "trend_compare_up": "This week is {ratio}× of last week.",
        "trend_marker_new": "new",
        "trend_section": "Weekly burn trail",
        "unknown": "unknown",
        "version": "version",
    },
    "ja": {
        "active_days": "活動日",
        "cost": "費用",
        "duration": "時間",
        "empty_models": "この期間のモデル使用量はありません",
        "empty_projects": "この期間のプロジェクト使用量はありません",
        "empty_daily": "この期間の日別使用量はありません",
        "empty_sessions": "この期間に表示できるセッションはありません",
        "footer": "token-tracker · ローカル分析 · データは端末内に留まる",
        "generated": "生成日時",
        "kpi_active": "活動日",
        "kpi_cost": "使った費用",
        "kpi_messages": "メッセージ",
        "kpi_sessions": "セッション",
        "kpi_tokens": "使った Tokens",
        "messages": "メッセージ",
        "model": "モデル",
        "model_section": "よく一緒に使ったモデル",
        "narrative": "この期間に {tokens} tokens を使い、{projects} 件のプロジェクトを横断し、ピークは {peak_date}（{peak_tokens}/日）。最もよく一緒に使ったのは {top_model} です。",
        "period": "期間",
        "project": "プロジェクト",
        "project_section": "プロジェクトのホットゾーン",
        "rank": "順位",
        "session_section": "使用量が大きい 5 セッション",
        "sessions": "セッション",
        "share": "割合",
        "start_time": "開始時刻",
        "title": "AI 使用量の振り返り",
        "tokens": "Tokens",
        "trend_compare_down": "今週は先週より {pct}% 少なくなりました。",
        "trend_compare_first": "これはこの期間の最初の週のデータです。",
        "trend_compare_flat": "今週は先週とほぼ同じです。",
        "trend_compare_new": "今週は先週になかった新しい使用量です。",
        "trend_compare_up": "今週は先週の {ratio} 倍です。",
        "trend_marker_new": "new",
        "trend_section": "週次バーン推移",
        "unknown": "不明",
        "version": "バージョン",
    },
    "ko": {
        "active_days": "활동일",
        "cost": "비용",
        "duration": "시간",
        "empty_models": "이 기간에는 모델 사용량이 없습니다",
        "empty_projects": "이 기간에는 프로젝트 사용량이 없습니다",
        "empty_daily": "이 기간에는 일별 사용량이 없습니다",
        "empty_sessions": "이 기간에는 표시할 세션이 없습니다",
        "footer": "token-tracker · 로컬 분석 · 데이터는 기기에만",
        "generated": "생성 시간",
        "kpi_active": "활동일",
        "kpi_cost": "쓴 비용",
        "kpi_messages": "메시지",
        "kpi_sessions": "세션",
        "kpi_tokens": "쓴 Tokens",
        "messages": "메시지",
        "model": "모델",
        "model_section": "가장 자주 함께한 모델",
        "narrative": "이 기간에 {tokens} tokens를 썼고, {projects}개 프로젝트를 넘나들었으며, 최고점은 {peak_date}({peak_tokens}/일)였습니다. 가장 자주 함께한 모델은 {top_model}입니다.",
        "period": "기간",
        "project": "프로젝트",
        "project_section": "프로젝트 핫존",
        "rank": "순위",
        "session_section": "가장 많이 쓴 세션 5개",
        "sessions": "세션",
        "share": "비중",
        "start_time": "시작 시간",
        "title": "AI 사용량 리캡",
        "tokens": "Tokens",
        "trend_compare_down": "이번 주는 지난주보다 {pct}% 적습니다.",
        "trend_compare_first": "이번 기간의 첫 주 데이터입니다.",
        "trend_compare_flat": "이번 주는 지난주와 거의 비슷합니다.",
        "trend_compare_new": "이번 주에는 지난주에 없던 사용량이 생겼습니다.",
        "trend_compare_up": "이번 주는 지난주의 {ratio}배입니다.",
        "trend_marker_new": "new",
        "trend_section": "주간 사용 추이",
        "unknown": "알 수 없음",
        "version": "버전",
    },
}


def _fmt_tokens(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def _fmt_cost(value: float) -> str:
    return f"${value:,.4f}" if 0 < value < 1 else f"${value:,.2f}"


def _fmt_duration(minutes: float) -> str:
    if minutes >= 60:
        return f"{int(minutes // 60)}h {int(minutes % 60)}m"
    return f"{int(minutes)}m"


def _version() -> str:
    try:
        return version("token-tracker")
    except PackageNotFoundError:
        return "dev"


def _detect_lang(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    raw = source.get("TT_LANG", "").strip() or source.get("LANG", "")
    code = raw.split(".")[0].replace("_", "-")

    if code in {"zh-TW", "zh-HK"}:
        return "zh-TW"
    if code in {"zh-CN", "zh-SG", "zh"}:
        return "zh-CN"
    if code.startswith("en"):
        return "en"
    if code.startswith("ja"):
        return "ja"
    if code.startswith("ko"):
        return "ko"
    return "en"


def _t(lang: str, key: str) -> str:
    return REPORT_TRANSLATIONS.get(lang, REPORT_TRANSLATIONS["en"])[key]


def _escape(value: object) -> str:
    return html.escape(str(value))


def _display_name(value: object, lang: str) -> str:
    text = str(value) if value else _t(lang, "unknown")
    return _t(lang, "unknown") if text == "unknown" else text


def _section(title: str, body: str) -> str:
    return f"""
    <section class="section">
      <div class="prompt"><span>[token-tracker]&gt;</span> {html.escape(title)}</div>
      <div class="rule" aria-hidden="true">────────────────────────────────────────────────────────</div>
      {body}
    </section>
    """


def _empty_line(label: str) -> str:
    return f'<div class="empty">→ {html.escape(label)}</div>'


def _rank_line(name: str, pct: float, tokens: int, cost: float) -> str:
    return (
        '<div class="rank-line">'
        f'<span class="arrow">→</span><span class="name">{html.escape(name)}</span>'
        f'<span class="pct">{pct:>5.1f}%</span>'
        f'<span class="tokens">{_fmt_tokens(tokens)}</span>'
        f'<span class="cost">{_fmt_cost(cost)}</span>'
        "</div>"
    )


def _parse_daily_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _weekly_trend(daily: list[dict]) -> list[dict[str, int | float]]:
    weekly: dict[tuple[int, int], dict[str, int | float]] = {}
    for day in daily:
        parsed = _parse_daily_date(day["date"])
        iso_year, iso_week, _weekday = parsed.isocalendar()
        key = (iso_year, iso_week)
        bucket = weekly.setdefault(key, {"year": iso_year, "week": iso_week, "tokens": 0, "cost": 0.0})
        bucket["tokens"] = int(bucket["tokens"]) + int(day.get("tokens", 0))
        bucket["cost"] = float(bucket["cost"]) + float(day.get("cost", 0.0))
    return [weekly[key] for key in sorted(weekly)]


def _trend_delta(current: int, previous: int, lang: str) -> tuple[str, str]:
    if previous == 0:
        if current == 0:
            return "flat", "→ 0%"
        return "up", f"↗ {_t(lang, 'trend_marker_new')}"

    pct = round((current - previous) / previous * 100)
    if abs(pct) <= 5:
        return "flat", "→ 0%"
    if pct > 0:
        return "up", f"↗ +{pct}%"
    return "down", f"↘ {pct}%"


def _trend_summary(weekly: list[dict[str, int | float]], lang: str) -> str:
    if len(weekly) < 2:
        return f"→ {_t(lang, 'trend_compare_first')}"

    current = int(weekly[-1]["tokens"])
    previous = int(weekly[-2]["tokens"])
    if previous == 0:
        if current == 0:
            return f"→ {_t(lang, 'trend_compare_flat')}"
        return f"→ {_t(lang, 'trend_compare_new')}"

    pct = round((current - previous) / previous * 100)
    if abs(pct) <= 5:
        return f"→ {_t(lang, 'trend_compare_flat')}"
    if pct > 0:
        return f"→ {_t(lang, 'trend_compare_up').format(ratio=f'{current / previous:.1f}')}"
    return f"→ {_t(lang, 'trend_compare_down').format(pct=abs(pct))}"


def _trend_ascii(daily: list[dict], lang: str) -> str:
    weekly = _weekly_trend(daily)
    max_tokens = max((int(week["tokens"]) for week in weekly), default=0)
    rows = []
    for idx, week in enumerate(weekly):
        tokens = int(week["tokens"])
        filled = max(1, round(tokens / max_tokens * 12)) if max_tokens and tokens else 0
        bar = "█" * filled
        delta_html = '<span class="delta flat"></span>'
        if idx > 0:
            delta_class, delta_label = _trend_delta(tokens, int(weekly[idx - 1]["tokens"]), lang)
            delta_html = f'<span class="delta {delta_class}">{_escape(delta_label)}</span>'
        rows.append(
            '<div class="trend-row">'
            f'<span class="week">W{int(week["week"])}</span>'
            f'<b>{bar}</b>'
            f'<em>{_fmt_tokens(tokens)}</em>'
            f"{delta_html}"
            "</div>"
        )
    if not rows:
        return _empty_line(_t(lang, "empty_daily"))

    trend_rows = "".join(rows)
    summary = f'<div class="trend-summary">{_escape(_trend_summary(weekly, lang))}</div>'
    return f'<div class="trend">{trend_rows}{summary}</div>'


def _narrative(data: dict, lang: str) -> str:
    summary = data["summary"]
    daily = data.get("daily_trend", [])
    peak = max(daily, key=lambda day: int(day["tokens"]), default={"date": data.get("date_to", "---- -- --"), "tokens": 0})
    top_model = data.get("by_model", [{}])[0].get("model", _t(lang, "unknown")) if data.get("by_model") else _t(lang, "unknown")
    return _t(lang, "narrative").format(
        tokens=_fmt_tokens(int(summary["total_tokens"])),
        projects=len(data.get("by_project", [])),
        peak_date=str(peak["date"]),
        peak_tokens=_fmt_tokens(int(peak["tokens"])),
        top_model=_display_name(top_model, lang),
    )


def _cost_value(cost_usd: float, lang: str) -> tuple[str, str]:
    main = _fmt_cost(cost_usd)
    sub = f"≈ NT${cost_usd * 32:,.0f}" if lang == "zh-TW" else ""
    return main, sub


def generate_html(data: dict) -> str:
    lang = _detect_lang()
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    summary = data["summary"]
    total_tokens = int(summary["total_tokens"])
    cost_main, cost_sub = _cost_value(float(summary["cost_usd"]), lang)
    cards = [
        (_t(lang, "kpi_tokens"), f"{total_tokens:,}", f"≈ {_fmt_tokens(total_tokens)}"),
        (_t(lang, "kpi_cost"), cost_main, cost_sub),
        (_t(lang, "kpi_sessions"), f'{int(summary["sessions"]):,}', ""),
        (_t(lang, "kpi_messages"), f'{int(summary["messages"]):,}', ""),
        (_t(lang, "kpi_active"), f'{int(summary["active_days"])}/{int(summary["total_days"])}', ""),
    ]

    project_rows = [
        _rank_line(
            _display_name(project["project"], lang),
            float(project["pct"]),
            int(project["tokens"]),
            float(project["cost"]),
        )
        for project in data.get("by_project", [])
    ]
    project_rows_html = "".join(project_rows)
    project_body = (
        f'<div class="rank-head"><span></span><span>{_escape(_t(lang, "project"))}</span><span>{_escape(_t(lang, "share"))}</span><span>{_escape(_t(lang, "tokens"))}</span><span>{_escape(_t(lang, "cost"))}</span></div>'
        f'<div class="rank-list">{project_rows_html}</div>'
        if project_rows
        else _empty_line(_t(lang, "empty_projects"))
    )

    model_rows = [
        _rank_line(
            _display_name(model["model"], lang),
            float(model["pct"]),
            int(model["tokens"]),
            float(model["cost"]),
        )
        for model in data.get("by_model", [])
    ]
    model_rows_html = "".join(model_rows)
    model_body = (
        f'<div class="rank-head"><span></span><span>{_escape(_t(lang, "model"))}</span><span>{_escape(_t(lang, "share"))}</span><span>{_escape(_t(lang, "tokens"))}</span><span>{_escape(_t(lang, "cost"))}</span></div>'
        f'<div class="rank-list">{model_rows_html}</div>'
        if model_rows
        else _empty_line(_t(lang, "empty_models"))
    )

    session_rows = []
    for idx, session in enumerate(data.get("top_sessions", []), 1):
        session_rows.append(f"""
        <tr>
          <td>#{idx}</td>
          <td>{_escape(session["start_time"])}</td>
          <td>{_escape(_display_name(session["project"], lang))}</td>
          <td>{_escape(_display_name(session["model"], lang))}</td>
          <td>{_fmt_duration(float(session["duration_min"]))}</td>
          <td>{_fmt_tokens(int(session["tokens"]))}</td>
          <td>{_fmt_cost(float(session["cost"]))}</td>
        </tr>""")
    session_body = (
        f"""
        <div class="table-wrap">
          <table>
            <thead><tr><th>{_escape(_t(lang, "rank"))}</th><th>{_escape(_t(lang, "start_time"))}</th><th>{_escape(_t(lang, "project"))}</th><th>{_escape(_t(lang, "model"))}</th><th>{_escape(_t(lang, "duration"))}</th><th>{_escape(_t(lang, "tokens"))}</th><th>{_escape(_t(lang, "cost"))}</th></tr></thead>
            <tbody>{''.join(session_rows)}</tbody>
          </table>
        </div>
        """
        if session_rows
        else _empty_line(_t(lang, "empty_sessions"))
    )

    title = _t(lang, "title")
    return f"""<!doctype html>
<html lang="{html.escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root{{--bg:#050505;--panel:#0d0f12;--soft:#15181d;--text:#f2f4f8;--muted:#8b949e;--faint:#343941;--token:#58a6ff;--cost:#3fb950;--warn:#d29922;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;line-height:1.55}}
.wrap{{max-width:960px;margin:0 auto;padding:42px 22px 34px}}
header{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:28px;align-items:start;margin-bottom:26px}}
h1{{margin:0 0 10px;font-size:clamp(1.8rem, 4.2vw, 3rem);line-height:1.02;font-weight:800;letter-spacing:-0.02em;white-space:nowrap}}
.eyebrow,.meta,.empty,footer{{color:var(--muted)}}
.eyebrow span,.prompt span,.cursor{{color:var(--token)}}
.cursor{{display:inline-block;animation:blink 1s steps(2,start) infinite}}
.narrative{{max-width:760px;margin:18px 0 0;color:#d5dbe4;font-size:1.02rem}}
.meta{{font-size:.82rem;text-align:right;white-space:nowrap}}
.cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:22px 0 12px}}
.card{{background:var(--panel);padding:16px 14px;border-radius:6px;min-height:108px;display:flex;flex-direction:column}}
.card span{{display:block;color:var(--muted);font-size:.75rem;text-transform:uppercase;margin-bottom:10px}}
.card b{{display:block;font-size:clamp(.95rem,1.4vw,1.2rem);color:var(--text);overflow-wrap:anywhere;line-height:1.2;font-weight:700;letter-spacing:-0.01em}}
.card i{{display:block;font-style:normal;color:var(--muted);font-size:.72rem;margin-top:auto;padding-top:6px;overflow-wrap:anywhere;letter-spacing:0}}
.card:first-child b{{color:var(--token)}}.card:nth-child(2) b{{color:var(--cost)}}
.section{{background:var(--panel);border-radius:8px;margin-top:16px;padding:18px 16px}}
.prompt{{font-size:.95rem;color:#f0f6fc;margin-bottom:4px}}
.rule{{color:var(--faint);white-space:nowrap;overflow:hidden;margin-bottom:14px}}
.rank-head,.rank-line{{display:grid;grid-template-columns:24px minmax(0,1fr) 72px 92px 88px;gap:12px;align-items:center}}
.rank-head{{color:var(--muted);font-size:.74rem;text-transform:uppercase;margin-bottom:8px}}
.rank-head>span:nth-child(n+3){{text-align:right}}
.rank-line{{padding:7px 0;color:#dce2ea}}
.arrow{{color:var(--warn)}}.name{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.pct{{color:var(--token)}}.cost{{color:var(--cost)}}.tokens,.cost,.pct{{text-align:right;white-space:nowrap}}
.trend{{display:grid;gap:6px}}
.trend-row{{display:grid;grid-template-columns:58px minmax(0,1fr) 72px 82px;gap:12px;align-items:center}}
.trend-row .week{{color:var(--muted)}}.trend-row b{{color:var(--token);font-weight:400;white-space:nowrap;overflow:hidden}}.trend-row em{{font-style:normal;text-align:right;color:#dce2ea}}.delta{{color:var(--muted);white-space:nowrap}}.delta.up{{color:var(--cost)}}.delta.down{{color:var(--warn)}}.delta.flat{{color:var(--muted)}}.trend-summary{{color:#dce2ea;margin-top:8px}}
.table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:760px}}th,td{{padding:8px 10px;text-align:left;font-size:.86rem}}th{{color:var(--muted);font-weight:500;text-transform:uppercase}}td{{color:#dce2ea}}td:first-child{{color:var(--warn)}}
footer{{text-align:center;font-size:.82rem;margin-top:22px}}
@keyframes blink{{0%,45%{{opacity:1}}46%,100%{{opacity:0}}}}
@media (max-width:780px){{.wrap{{padding:28px 14px}}header{{display:block}}.meta{{text-align:left;margin-top:16px}}.cards{{grid-template-columns:repeat(2,1fr)}}.rank-head,.rank-line{{grid-template-columns:24px minmax(0,1fr) 64px}}.rank-head span:nth-child(4),.rank-head span:nth-child(5),.rank-line span:nth-child(4),.rank-line span:nth-child(5){{display:none}}}}
</style>
</head>
<body>
<main class="wrap">
  <header>
    <div>
      <div class="eyebrow"><span>$</span> tt report --period {html.escape(str(data["period_label"]))}<span class="cursor">_</span></div>
      <h1>{html.escape(title)}</h1>
      <p class="narrative">{html.escape(_narrative(data, lang))}</p>
    </div>
    <div class="meta">{html.escape(_t(lang, "generated"))} {html.escape(generated_at)}<br>token-tracker {_escape(_t(lang, "version"))} {_escape(_version())}</div>
  </header>
  <section class="cards">{''.join(f'<div class="card"><span>{html.escape(label)}</span><b>{html.escape(value)}</b>' + (f'<i>{html.escape(sub)}</i>' if sub else '') + '</div>' for label, value, sub in cards)}</section>
  {_section(_t(lang, "project_section"), project_body)}
  {_section(_t(lang, "model_section"), model_body)}
  {_section(_t(lang, "trend_section"), _trend_ascii(data.get("daily_trend", []), lang))}
  {_section(_t(lang, "session_section"), session_body)}
  <footer>{html.escape(_t(lang, "footer"))}</footer>
</main>
</body>
</html>
"""


def save_and_open(data: dict, out_path: str | None = None) -> str:
    if out_path:
        path = Path(os.path.expanduser(out_path))
        display_path = str(path.expanduser())
    else:
        reports_dir = Path.home() / ".tt-reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"tt-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html"
        display_path = f"~/.tt-reports/{path.name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_html(data), encoding="utf-8")
    if out_path is None:
        webbrowser.open(path.resolve().as_uri())
    return display_path
