"""CSS for the HTML usage report. Extracted verbatim from html_report."""

def _light_rules(rules: str) -> str:
    """Emit both theme paths from flat rules, preserving cascade specificity/order."""
    def scoped(scope: str) -> str:
        result = []
        for rule in rules.strip().split("}"):
            if not rule.strip():
                continue
            selectors, declarations = rule.split("{", 1)
            prefixed = []
            for selector in selectors.split(","):
                selector = selector.strip()
                prefixed.append(
                    f":root:where({scope})" if selector == ":root"
                    else f":where(html{scope}) {selector}"
                )
            result.append(",".join(prefixed) + "{" + declarations + "}")
        return "\n".join(result)

    return (
        "@media (prefers-color-scheme: light){\n" + scoped(":not([data-theme])")
        + "\n}\n" + scoped('[data-theme="light"]')
    )


REPORT_CSS = ("""/* Hallmark · macrostructure: Stat-led report · brand: usage (preserved)
 * pre-emit critique: P5 H4 E4 S5 R5 V4 */
:root{
  --font-mono:ui-monospace,SFMono-Regular,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
  --bg:#0b0908;
  --bg-gradient-1:rgba(224,154,88,.055);
  --bg-gradient-2:rgba(90,191,160,.12);
  --panel:rgba(23,19,14,.94);
  --card-bg:rgba(23,19,14,.96);
  --card-border:rgba(255,255,255,.14);
  --card-shadow:rgba(0,0,0,.4);
  --control-hover:rgba(255,255,255,.12);
  --hover-glow:rgba(255,255,255,.07);
  --disabled-bg:rgba(255,255,255,.03);
  --soft:rgba(34,28,20,.45);
  --text:#f5f2ec;
  --text-soft:#ddd6c8;
  --muted:#a39a8a;
  --faint:rgba(255,255,255,.08);
  --token:#e8c66a;
  --cost:#5abfa0;
  --warn:#e0885a;
  --accent-purple:#8f86c9;
  --noise-img:url("data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgMjAwIDIwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KICA8ZmlsdGVyIGlkPSJub2lzZSI+CiAgICA8ZmVUdXJidWxlbmNlIHR5cGU9ImZyYWN0YWxOb2lzZSIgYmFzZUZyZXF1ZW5jeT0iMC44NSIgbnVtT2N0YXZlcz0iNCIgc3RpdGNoVGlsZXM9InN0aXRjaCIvPgogIDwvZmlsdGVyPgogIDxyZWN0IHdpZHRoPSIxMDAlIiBoZWlnaHQ9IjEwMCUiIGZpbHRlcj0idXJsKCNub2lzZSkiIG9wYWNpdHk9IjAuMDQiLz4KPC9zdmc+");
  --glass-blur:12px;
  --contrib-0:rgba(255,255,255,.05);
  --contrib-1:rgba(90,191,160,.22);
  --contrib-2:rgba(90,191,160,.42);
  --contrib-3:rgba(90,191,160,.68);
  --contrib-4:rgba(90,191,160,.95);
}

""" + _light_rules("""
  :root{
    --bg:#f6f2e9;
    --bg-gradient-1:rgba(176,90,43,.035);
    --bg-gradient-2:rgba(46,125,104,.08);
    --panel:rgba(255,253,246,.96);
    --card-bg:rgba(255,253,246,.98);
    --card-border:#918471;
    --card-shadow:rgba(31,41,55,.06);
    --control-hover:rgba(67,57,42,.1);
    --hover-glow:rgba(31,41,55,.08);
    --disabled-bg:rgba(107,97,81,.08);
    --soft:rgba(240,234,220,.7);
    --text:#292317;
    --text-soft:#43392a;
    --muted:#6b6151;
    --faint:rgba(0,0,0,.06);
    --token:#8a6a1c;
    --cost:#2e7d68;
    --warn:#b05a2b;
    --accent-purple:#68609b;
    --noise-img:url("data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgMjAwIDIwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KICA8ZmlsdGVyIGlkPSJub2lzZSI+CiAgICA8ZmVUdXJidWxlbmNlIHR5cGU9ImZyYWN0YWxOb2lzZSIgYmFzZUZyZXF1ZW5jeT0iMC44NSIgbnVtT2N0YXZlcz0iNCIgc3RpdGNoVGlsZXM9InN0aXRjaCIvPgogIDwvZmlsdGVyPgogIDxyZWN0IHdpZHRoPSIxMDAlIiBoZWlnaHQ9IjEwMCUiIGZpbHRlcj0idXJsKCNub2lzZSkiIG9wYWNpdHk9IjAuMDE4Ii8+Cjwvc3ZnPg==");
    --glass-blur:16px;
    --contrib-0:rgba(0,0,0,.05);
    --contrib-1:rgba(46,125,104,.20);
    --contrib-2:rgba(46,125,104,.40);
    --contrib-3:rgba(46,125,104,.65);
    --contrib-4:rgba(46,125,104,.92);
  }
  .share-bar span[style*="background:#5abfa0"]{background:#2e7d68!important}
  .share-bar span[style*="background:#8f86c9"]{background:#68609b!important}
  .share-bar span[style*="background:#e0885a"]{background:#b05a2b!important}
  .share-bar span[style*="background:#8b8577"]{background:#6b6151!important}
""") + """

html{font-size:17.5px}
html,body{overflow-x:clip}
*{box-sizing:border-box}
body{
  margin:0;
  background-color:var(--bg);
  background-image:var(--noise-img),radial-gradient(circle at 15% 20%,var(--bg-gradient-1) 0%,transparent 45%),radial-gradient(circle at 85% 75%,var(--bg-gradient-2) 0%,transparent 45%);
  background-attachment:fixed;
  background-size:auto,100% 100%,100% 100%;
  color:var(--text);
  font-family:"Styrene A","Styrene B","Helvetica Neue",system-ui,sans-serif;
  line-height:1.55;
  -webkit-font-smoothing:antialiased;
  -moz-osx-font-smoothing:grayscale;
}
.wrap{max-width:1140px;margin:0 auto;padding:36px 24px}
header{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:28px;align-items:start;margin-bottom:32px}
h1,.prompt,.share-modal h2,.share-section h3,.persona-card h3,.ai-update-head h3{
  font-family:"Grenette",Georgia,serif;
}
h1{
  margin:0 0 12px;
  font-size:clamp(2rem,5vw,3.2rem);
  line-height:1.05;
  font-weight:800;
  letter-spacing:-.03em;
  white-space:nowrap;
  color:var(--text);
}
.eyebrow,.meta,.empty,footer,.cursor,.prompt,.share-trigger,.share-close,.share-action,.tokens,.cost,.pct,.trend-row .week,.trend-row em,.delta,.donut-total,.donut-sub,.sub-plan,.sub-since,.ai-update-version,.ai-update-period,th,td,.wrapped-kicker,.wrapped-total-label,.contribution-months,.contribution-days,.contribution-legend{
  font-family:var(--font-mono);
}
.eyebrow,.meta,.empty,footer{color:var(--muted)}
.eyebrow span,.prompt span{color:var(--cost)}
.cursor{color:var(--token)}
.cursor{display:inline-block;animation:blink 1.2s steps(2,start) infinite}
.narrative{max-width:760px;margin:18px 0 0;color:var(--text-soft);font-size:1.02rem;line-height:1.6}
/* 吸在視窗頂端：報表很長，捲到一半想換區間不該再捲回最上面。 */
.date-filter{position:sticky;top:0;z-index:20;display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;margin:0 -24px 28px;padding:12px 24px;background:var(--bg);border-bottom:1px solid var(--card-border)}
.date-shortcuts,.date-inputs{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.date-filter button,.date-filter input{border:1px solid var(--card-border);border-radius:7px;background:var(--panel);color:var(--text);font:inherit;font-size:.76rem;line-height:1.3}
.date-filter button{padding:6px 10px;cursor:pointer}
.date-filter button[aria-pressed="true"]{border-color:var(--cost);color:var(--cost);background:var(--control-hover)}
.date-inputs label{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:.76rem}
.date-filter input{padding:5px 8px;color-scheme:dark}
.date-filter button:focus-visible,.date-filter input:focus-visible{outline:2px solid var(--cost);outline-offset:2px}
.meta{font-size:.82rem;text-align:right;white-space:nowrap;line-height:1.4}
.header-actions{display:flex;flex-direction:column;align-items:flex-end;justify-self:end;gap:12px;min-width:max-content}
.header-buttons{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}
.share-trigger{
  display:inline-flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--card-border);color:var(--text);padding:6px 14px;border-radius:8px;cursor:pointer;font-size:.8rem;font-weight:500;line-height:1.3;text-decoration:none;transition:background-color .2s ease,border-color .2s ease,color .2s ease,transform .2s ease,box-shadow .2s ease,opacity .2s ease
}
.share-trigger:hover{border-color:rgba(255,255,255,.24);color:var(--text);background:var(--control-hover);transform:translateY(-2px);box-shadow:0 4px 12px var(--hover-glow)}
""" + _light_rules("""
  .share-trigger:hover{border-color:var(--text-soft)}
""") + """
.share-trigger:focus-visible,.share-close:focus-visible,.share-action:focus-visible,.rank-line[tabindex]:focus-visible{outline:2px solid var(--cost);outline-offset:2px}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;margin:24px 0 32px;border-block:1px solid var(--card-border);background:var(--card-bg)}
.cards:has([data-card]){grid-template-columns:repeat(3,minmax(0,1fr))}
.cards:has([data-card]) .card:nth-child(4){border-left:0}
.cards:has([data-card]) .card:nth-child(n+4){border-top:1px solid var(--card-border)}
.card{padding:20px 16px;min-width:0;display:grid;grid-template-rows:minmax(2.2em,auto) auto minmax(2.8em,auto);align-content:start}
.card+.card{border-left:1px solid var(--card-border)}
.card span{display:block;color:var(--muted);font-size:.78rem;font-weight:600;line-height:1.4;text-transform:uppercase;letter-spacing:.06em;padding-bottom:10px}
.card b{display:block;min-width:0;font-family:var(--font-mono);font-size:clamp(1.2rem,2.1vw,1.6rem);color:var(--text);overflow-wrap:anywhere;line-height:1.2;font-weight:700;letter-spacing:-.04em;font-variant-numeric:tabular-nums}
.card i{display:block;font-style:normal;color:var(--muted);font-size:.78rem;line-height:1.5;padding-top:10px;overflow-wrap:anywhere}
.card:first-child b{color:var(--token)}
.card:nth-child(2) b{color:var(--cost)}
.cards:not(:has(.card:nth-child(4))){grid-template-columns:repeat(auto-fit,minmax(0,1fr))}
/* Keep every numeric column on the same inset; vary surfaces and vertical rhythm. */
.section{background:transparent;border:1px solid transparent;border-radius:0;margin-top:32px;padding:20px;box-shadow:none}
.prompt{font-size:1.05rem;color:var(--text);margin-bottom:12px;font-weight:600;display:flex;flex-wrap:wrap;align-items:baseline;gap:8px;min-width:0;overflow-wrap:anywhere}
.prompt span{font-size:.72rem;font-weight:400}
.prompt .prompt-title{font:inherit;color:inherit}
.fixed-range-tag{padding:1px 6px;border:1px solid var(--card-border);border-radius:999px;color:var(--muted);font-size:.64rem;font-weight:500;letter-spacing:.03em;white-space:nowrap}
.rule{font-size:0;height:1px;background:var(--card-border);margin-bottom:20px;border:none}
.insights-section{margin-block:24px;padding-block:8px}
.insights-section .rule,.wrapped-section .rule{height:0;margin-bottom:16px}
.insights-section .prompt{font-size:1.2rem}
.composition-section,.model-section{margin-top:8px;padding-top:8px}
.composition-section .prompt,.model-section .prompt,.recent-titles-section .prompt{font-size:.9rem}
.composition-section .rule,.model-section .rule,.recent-titles-section .rule{background:var(--faint);margin-bottom:12px}
.contribution-section{margin-top:40px;border-top-color:var(--card-border);padding-top:28px}
.contribution-section .rule{height:0;margin-bottom:24px}
.contribution-section .prompt{font-size:1.2rem}
.recent-titles-section{margin-top:16px;padding-block:12px}
.persona-section{background:var(--soft);border-block-color:var(--card-border)}
.session-section{margin-top:40px;border-top-color:var(--card-border)}
.rank-list{display:grid;gap:4px}
.composition-hint{margin:10px 0 14px;color:var(--text-soft)}
.rank-head,.rank-line{display:grid;grid-template-columns:20px minmax(0,1fr) 72px 100px 100px;gap:16px;align-items:center}
.rank-head{padding:0 12px 8px;color:var(--muted);font-size:.72rem;font-weight:600;line-height:1.4;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px}
.rank-head>span:nth-child(n+3){text-align:right}
.rank-line{position:relative;overflow:hidden;padding:12px;color:var(--text-soft);border:none;border-bottom:1px solid var(--card-border);border-radius:0;box-shadow:none;background:transparent;transition:transform .2s ease,background-color .2s ease,border-color .2s ease,box-shadow .2s ease}
.rank-line:hover{transform:none;border:none;border-bottom:1px solid var(--card-border);border-radius:0;box-shadow:none;background:transparent}
.rank-line:last-child{border-bottom:none}
.rank-line[data-agent-id],.rank-line[data-project-index]{cursor:pointer}
/* .rank-line 用 class 指定 display:grid，權重高過瀏覽器預設的 [hidden]{display:none}，
   沒有這一條收合只會改到 DOM、畫面照舊全開。 */
.rank-line[hidden]{display:none}
.composition-section[hidden]{display:none}
.rank-line.model-group .name{font-weight:600}
/* 展開的子列要一眼看出「屬於上面那一列」：整段壓深底色、左側加一條縱線
   框住，縮排拉大，長條也調淡，免得跟母列的長條搶視線。 */
.rank-line.model-child,.project-detail-caption{
  background:var(--soft);box-shadow:inset 3px 0 0 var(--warn)}
.rank-line.model-child .name,.rank-line.model-child .model-name{padding-left:34px}
.rank-line.model-child .share-bar span{opacity:.09}
.project-detail-caption{padding:8px 12px 4px 34px;color:var(--muted);font-size:.66rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase}
.arrow{color:var(--warn);opacity:.3;font-size:.8em}
/* 可點開的列：箭頭是唯一的可展開提示，用跟裝飾性箭頭一樣的淡度會看不出來。 */
.rank-line.model-group .arrow,.rank-line[data-project-index] .arrow{opacity:.85;font-size:1em;color:var(--text-soft)}
.rank-line>*,.tool-row>*{position:relative;z-index:1}
/* The bar is absolute against the whole row, so .name must stay static — this
   rule has to follow the one above to win. (.tool-head does the same further down.) */
.name,.model-name{position:static;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-soft);font-size:.9em;font-weight:normal}
.share-bar{position:absolute;top:0;left:0;width:100%;height:100%;margin:0;overflow:hidden;border-radius:0;background:transparent;z-index:0;pointer-events:none}
.share-bar span{display:block;height:100%;border-radius:0;background:var(--cost);opacity:.15}
.pct{color:var(--text-soft)}
.tokens,.tokens-cell{color:var(--token)}
.cost{color:var(--cost)}
.tokens,.cost{font-size:1.15rem;font-weight:700;font-variant-numeric:tabular-nums}
.tokens,.cost,.pct{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.trend{display:grid;gap:6px}
.trend-row{position:relative;isolation:isolate;display:grid;grid-template-columns:minmax(56px,1fr) 100px 100px;gap:16px;align-items:center;padding:12px;border-bottom:1px solid var(--card-border)}
.trend-row:last-of-type{border-bottom:none}
.trend-row .week{color:var(--muted);font-size:.78rem;line-height:1.4}
/* Same whole-row fill, opacity and square ends as .share-bar; retain its ratio. */
.trend-bar{position:absolute;inset:0;z-index:-1;overflow:hidden;pointer-events:none}
.trend-bar div{height:100%;background:var(--cost);opacity:.15}
.trend-row em{font-style:normal;text-align:right;color:var(--token);font-size:.82rem;font-variant-numeric:tabular-nums}
.delta{color:var(--muted);white-space:nowrap;text-align:right;justify-self:end;font-size:.78rem;font-weight:600;font-variant-numeric:tabular-nums}
.delta.up{color:var(--cost)}
.delta.down{color:var(--warn)}
.delta.flat{color:var(--muted)}
.trend-summary{color:var(--text-soft);margin-top:8px;padding-top:12px;border-top:1px solid var(--faint);font-size:.84rem;line-height:1.6}
""" + _light_rules("""
  .share-bar span,.trend-bar div{opacity:.22}
""") + """
/* Square, frameless fill in the same vocabulary as .share-bar and .trend-bar.
   The rounded box with a 3px accent rail read as a generic callout and was the
   last framed surface left in a report that strips frames everywhere else. */
.insight-note,.insight-action{padding:12px 14px;border-radius:0;margin-bottom:4px;font-size:.9rem;line-height:1.5}
.insight-note{background:rgba(90,191,160,.06);color:var(--text-soft)}
.insight-action{background:rgba(224,136,90,.06);color:var(--text-soft);margin-bottom:0}
/* No frame left to inset from, so only the vertical padding still earns its
   keep — the horizontal one just pushed this section 18px right of every other. */
.persona-card{border:none;border-radius:12px;box-shadow:none;background:transparent;padding:18px 0;min-width:0}
.persona-card+.persona-card{margin-top:16px}
.persona-card h3{margin:0 0 14px;color:var(--text);font-size:.95rem;font-weight:700}
.persona-caption{margin:0 0 16px;color:var(--text-soft);font-size:.88rem;line-height:1.5}
.persona-peak{margin-top:10px;text-align:right;color:var(--muted);font-size:.72rem;font-variant-numeric:tabular-nums}
.tokens-cell .share-bar{margin-top:5px;height:3px;max-width:96px;margin-left:auto}
.persona-hours{display:grid;grid-template-columns:repeat(24,minmax(8px,1fr));gap:4px;align-items:end;height:176px;padding-top:8px}
.persona-hour{display:grid;grid-template-rows:1fr auto;gap:7px;align-items:end;min-width:0;height:100%}
.persona-hour span{display:block;width:100%;min-height:1.5px;border-radius:4px 4px 1px 1px;background:linear-gradient(180deg,var(--cost),var(--accent-purple))}
.persona-hour.is-peak span{background:linear-gradient(180deg,var(--cost),var(--text-soft));box-shadow:0 0 12px rgba(90,191,160,.4)}
.persona-hour em{font-style:normal;color:var(--muted);font-size:.58rem;text-align:center;overflow:hidden}
.one-pass-list{display:grid;gap:12px}
.one-pass-row{display:grid;grid-template-columns:minmax(0,1fr) 128px 64px;gap:16px;align-items:center;color:var(--text-soft);font-size:.84rem}
.one-pass-row .name{min-width:0;overflow-wrap:anywhere;color:var(--text)}
.one-pass-row .turns,.one-pass-row strong{text-align:right;font-variant-numeric:tabular-nums}
.one-pass-row .turns{color:var(--muted);font-weight:500}
.one-pass-row strong{color:var(--text);font-size:.88rem}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:760px}
th,td{padding:8px 16px;text-align:left;font-size:.95rem}
th{color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--card-border)}
td{color:var(--text-soft);border-bottom:1px solid rgba(255,255,255,.03)}
""" + _light_rules("""
  td{border-bottom:1px solid rgba(0,0,0,.03)}
""") + """
td:first-child{color:var(--warn)}
.share-dialog{
  width:min(760px,calc(100vw - 28px));max-height:min(92vh,860px);border:1px solid var(--card-border);border-radius:12px;background:var(--panel);color:var(--text);padding:0;box-shadow:0 24px 70px rgba(0,0,0,.6);overflow:auto;backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px)
}
.share-dialog::backdrop{background:rgba(5,7,10,.72);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)}
""" + _light_rules("""
  .share-dialog::backdrop{background:rgba(243,244,246,.72)}
""") + """
.share-modal{position:relative;padding:24px;display:grid;gap:18px;align-content:start}
.share-modal h2{margin:0 40px 0 0;font-size:1.15rem;line-height:1.35;letter-spacing:0;font-weight:700}
.share-close{
  position:absolute;top:16px;right:16px;width:32px;height:32px;display:grid;place-items:center;border:1px solid var(--card-border);border-radius:8px;background:rgba(255,255,255,.06);color:var(--text);cursor:pointer;font-size:1.1rem;line-height:1;transition:background-color .2s ease,border-color .2s ease,color .2s ease,transform .2s ease,box-shadow .2s ease,opacity .2s ease
}
.share-close:hover{border-color:var(--cost);color:var(--cost);background:var(--control-hover)}
.share-section{border:1px solid var(--card-border);border-radius:10px;background:var(--soft);padding:16px;display:grid;gap:14px}
.share-section h3{margin:0;color:var(--text);font-size:.98rem;line-height:1.35;letter-spacing:0;font-weight:700}
.share-file-mask{display:inline-flex;align-items:center;gap:9px;color:var(--text-soft);font-size:.86rem;cursor:pointer;user-select:none}
.share-file-mask input{width:16px;height:16px;accent-color:var(--cost)}
.share-action{
  display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:38px;border:1px solid var(--card-border);border-radius:8px;background:rgba(255,255,255,.06);color:var(--text);cursor:pointer;font-size:.78rem;line-height:1.2;white-space:nowrap;transition:background-color .2s ease,border-color .2s ease,color .2s ease,transform .2s ease,box-shadow .2s ease,opacity .2s ease
}
.share-action:hover{border-color:var(--cost);color:var(--cost);background:var(--control-hover);transform:translateY(-1px)}
.share-trigger:active,.share-close:active,.share-action:active{transform:translateY(0);background:var(--control-hover);box-shadow:inset 0 1px 3px var(--card-shadow)}
.share-trigger:disabled,.share-close:disabled,.share-action:disabled{opacity:.55;cursor:not-allowed;transform:none;background:var(--disabled-bg);border-style:dashed;box-shadow:none;color:var(--muted)}
.share-trigger:disabled:hover,.share-close:disabled:hover,.share-action:disabled:hover{border-color:var(--card-border);background:var(--disabled-bg);color:var(--muted);transform:none;box-shadow:none}
.share-icon{color:var(--cost);display:inline-flex}
.share-icon svg{width:18px;height:18px;display:block;stroke-width:1.8}
.share-file-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.share-file-hint{margin:0;color:var(--muted);font-size:.8rem;line-height:1.5}
.share-toast{min-height:20px;color:var(--cost);font-size:.82rem;opacity:0;transition:opacity .2s ease}
.share-toast.show{opacity:1}
.sponsor{display:flex;justify-content:center;align-items:center;gap:18px;flex-wrap:wrap;padding:32px 16px 24px;color:var(--muted);font-size:.88rem}
.sponsor a{opacity:.8;transition:opacity .2s ease,transform .2s ease;display:inline-flex;text-decoration:none}
.sponsor a:hover{opacity:1;transform:scale(1.08)}
.sponsor img{vertical-align:middle;display:block}
.tagline{font-size:1rem;color:var(--text-soft);letter-spacing:.01em;animation:sponsorWobble 2.6s ease-in-out infinite;display:inline-block;transform-origin:center center}
.sponsor-link{text-align:center;padding:0 16px 32px;font-size:.8rem}
.sponsor-link a{color:var(--muted);text-decoration:none;opacity:.7;transition:color .2s ease,opacity .2s ease}
.sponsor-link a:hover{opacity:1;color:var(--cost)}
.sponsor a:focus-visible,.sponsor-link a:focus-visible{outline:2px solid var(--cost);outline-offset:4px;border-radius:4px}
.donut-wrap{display:flex;align-items:center;gap:32px;flex-wrap:wrap;margin-bottom:20px}
.donut{width:190px;height:190px;flex:0 0 auto}
.donut circle{transition:stroke-dashoffset .3s ease}
.donut-total{fill:var(--text);font-size:20px;font-weight:700}
.donut-sub{fill:var(--muted);font-size:11px;text-transform:uppercase}
.donut-legend{list-style:none;margin:0;padding:0;display:grid;gap:10px;flex:1 1 200px;min-width:200px}
.donut-legend li{display:grid;grid-template-columns:12px minmax(0,1fr) auto;gap:12px;align-items:center;font-size:.86rem;color:var(--text-soft)}
.donut-legend .dot{width:10px;height:10px;border-radius:3px}
.donut-legend .lg-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.donut-legend .lg-pct{color:var(--muted);text-align:right;font-weight:600}
.tools{display:grid;gap:12px;border:none;box-shadow:none;background:transparent}
.tools-head,.tool-row{display:grid;grid-template-columns:20px minmax(0,1fr) 72px 100px 100px;gap:16px;align-items:center}
.tools-head{padding:0 16px;color:var(--muted);font-size:.74rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:-2px}
.tools-head>span:nth-child(n+2),.rank-head>span:nth-child(n+3){text-align:right}
.tool-row{position:relative;overflow:hidden;padding:12px;border:none;border-bottom:1px solid var(--card-border);border-radius:0;background:transparent;box-shadow:none;transition:transform .25s cubic-bezier(.4,0,.2,1),border-color .25s cubic-bezier(.4,0,.2,1),box-shadow .25s cubic-bezier(.4,0,.2,1)}
.tool-row:hover{transform:none;border:none;border-bottom:1px solid var(--card-border);border-radius:0;background:transparent;box-shadow:none}
.tool-row:last-child{border-bottom:none}
.tool-head{position:static;display:flex;align-items:center;gap:14px;flex-wrap:wrap;min-width:0;color:var(--text-soft);font-size:.9em;font-weight:normal}
.sub-agent{font-weight:700;color:var(--text)}
.sub-plan{color:var(--text-soft);background:transparent;padding:3px 11px;border-radius:999px;font-size:.82rem;font-weight:600;border:1px solid var(--card-border)}
""" + _light_rules("""
  .sub-plan{background:rgba(255,255,255,.28);border-color:rgba(0,0,0,.12)}
""") + """
.sub-since{color:var(--muted);font-size:.82rem}
.tool-row .pct,.tool-row .tokens,.tool-row .cost{white-space:nowrap;text-align:right}
.tool-row .pct{color:var(--text-soft);font-weight:600}
.tool-row .tokens{color:var(--token)}
.tool-row .cost{color:var(--cost);font-weight:600}
.ai-updates-grid{display:grid;gap:16px}
.ai-update-card{padding:18px;border:1px solid var(--card-border);border-radius:12px;background:var(--soft)}
.ai-update-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.ai-update-head h3{margin:0;color:var(--text);font-size:1.05rem;line-height:1.35;font-weight:700}
.ai-update-version{color:var(--text-soft);font-size:.84rem;font-weight:600;white-space:nowrap}
.ai-update-period{margin:8px 0 0;color:var(--muted);font-size:.82rem}
.ai-update-items{list-style:none;display:grid;gap:14px;margin:16px 0 0;padding:0;counter-reset:ai-updates}
.ai-update-item{position:relative;counter-increment:ai-updates;padding:16px 16px 14px 48px;border:1px solid var(--card-border);border-radius:10px;background:rgba(0,0,0,.2);box-shadow:inset 0 1px 0 rgba(255,255,255,.03)}
""" + _light_rules("""
  .ai-update-item{background:rgba(255,255,255,.4);box-shadow:inset 0 1px 0 rgba(255,255,255,.5)}
""") + """
.ai-update-item:nth-child(even){background:rgba(0,0,0,.1)}
""" + _light_rules("""
  .ai-update-item:nth-child(even){background:rgba(255,255,255,.2)}
""") + """
.ai-update-item::before{content:counter(ai-updates,decimal-leading-zero);position:absolute;top:16px;left:16px;color:var(--muted);font-size:.72rem;font-weight:700;letter-spacing:.08em;line-height:1}
.ai-update-item-title{margin:0;color:var(--text);font-size:.92rem;font-weight:700;line-height:1.5}
.ai-update-item-body{margin:6px 0 0;color:var(--text-soft);font-size:.9rem;line-height:1.65}
.ai-update-original,.ai-update-history{margin-top:10px;border:1px solid var(--card-border);border-radius:8px;background:rgba(0,0,0,.15)}
""" + _light_rules("""
  .ai-update-original,.ai-update-history{background:rgba(255,255,255,.35)}
""") + """
.ai-update-original summary,.ai-update-history summary{cursor:pointer;list-style:none;padding:8px 12px;color:var(--text-soft);font-size:.82rem;font-weight:600;user-select:none;display:flex;align-items:center;gap:6px}
.ai-update-original summary::before,.ai-update-history summary::before{content:"▶";font-size:.65rem;transition:transform .25s ease;display:inline-block}
.ai-update-original[open] summary::before,.ai-update-history[open] summary::before{transform:rotate(90deg)}
.ai-update-original summary::-webkit-details-marker,.ai-update-history summary::-webkit-details-marker{display:none}
.ai-update-original[open] summary,.ai-update-history[open] summary{border-bottom:1px solid var(--card-border)}
.ai-update-original div{padding:12px;color:var(--muted);font-size:.82rem;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}
.ai-update-history>div{padding:12px;display:grid;gap:12px}
.ai-update-history-period{padding-left:12px;border-left:2px solid var(--card-border)}
.ai-update-history-period .ai-update-period{margin:0;color:var(--muted);font-size:.78rem}
.ai-update-history-items{list-style:none;display:grid;gap:10px;margin:8px 0 0;padding:0}
.ai-update-history-item{padding:0}
.ai-update-history-item .ai-update-item-title{font-size:.86rem}
.ai-update-history-item .ai-update-item-body{font-size:.84rem;color:var(--text-soft)}
.wrapped-section{background:var(--panel);border-block:1px solid var(--card-border);padding:24px 20px 28px}
.wrapped-card{display:grid;grid-template-columns:minmax(0,1fr) 188px;gap:32px;align-items:center}
.wrapped-copy,.wrapped-metrics{min-width:0}
.wrapped-kicker{color:var(--muted);font-size:.78rem;letter-spacing:.06em;text-transform:uppercase}
.wrapped-copy h3{font-family:var(--font-mono);margin:12px 0 8px;font-size:clamp(1.6rem,3vw,2.4rem);line-height:1.15;letter-spacing:-.03em;font-weight:700;color:var(--text);overflow-wrap:anywhere}
.wrapped-beast-line{margin:0;color:var(--warn);font-size:.95rem;line-height:1.5}
.wrapped-total{font-family:var(--font-mono);margin-top:20px;font-size:clamp(1.5rem,3vw,2.4rem);line-height:1.2;font-weight:700;letter-spacing:-.04em;color:var(--token);overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.wrapped-total-label{margin:8px 0 0;color:var(--muted);font-size:.8rem;text-transform:uppercase;letter-spacing:.06em}
.wrapped-analogy{margin:10px 0 0;color:var(--text-soft);font-size:.9rem;line-height:1.55}
.wrapped-art{display:grid;place-items:center;min-width:0}
.wrapped-art img{display:block;width:188px;max-width:100%;height:auto}
""" + _light_rules("""
  .wrapped-art img{filter:invert(1) opacity(.8)}
""") + """
.wrapped-metrics{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) repeat(2,minmax(0,1.3fr));gap:16px;border-top:1px solid var(--card-border);padding-top:20px}
.wrapped-metric{min-width:0}
.wrapped-metric span{display:block;color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
.wrapped-metric b{display:block;font-family:var(--font-mono);color:var(--text);font-size:1rem;line-height:1.35;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.wrapped-metric:first-child b{color:var(--cost)}
.contribution-wrap{display:grid;gap:16px;align-items:start}
.contribution-heatmap{min-width:0}
.contribution-months{display:grid;grid-template-columns:repeat(var(--weeks),minmax(0,18px));justify-content:start;gap:3px;padding-left:30px;margin-bottom:8px;color:var(--muted);font-size:.7rem;letter-spacing:.01em}
.contribution-months span{min-height:1em;white-space:nowrap;overflow:visible}
.contribution-board{display:grid;grid-template-columns:24px minmax(0,1fr);gap:6px;align-items:stretch}
.contribution-days{display:grid;grid-template-rows:repeat(7,1fr);gap:3px;color:var(--muted);font-size:.6rem;line-height:1;padding-top:0}
.contribution-grid{display:grid;grid-template-columns:repeat(var(--weeks),minmax(0,18px));grid-template-rows:repeat(7,auto);grid-auto-flow:column;gap:3px;justify-content:start}
.contribution-cell{display:block;width:100%;aspect-ratio:1;border-radius:2px;background:var(--contrib-0);border:1px solid var(--card-border)}
.contribution-cell.level-1{background:var(--contrib-1)}
.contribution-cell.level-2{background:var(--contrib-2)}
.contribution-cell.level-3{background:var(--contrib-3)}
.contribution-cell.level-4{background:var(--contrib-4)}
.contribution-cell.snake-body{background:var(--token);border-color:var(--token)}
.contribution-cell.snake-head{background:#fff;border-color:#fff;box-shadow:0 0 14px 4px var(--token);transform:scale(1.35);position:relative;z-index:1}
.contribution-section .prompt{cursor:pointer;user-select:none;transition:color .2s}
.contribution-section .prompt:hover{color:var(--token)}
.contribution-legend{display:flex;justify-content:flex-end;align-items:center;gap:6px;margin-top:12px;color:var(--muted);font-size:.72rem}
.contribution-legend .contribution-cell{width:12px;min-width:12px;height:12px;aspect-ratio:auto}
.contribution-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.contribution-stat{padding:16px 0;border-top:1px solid var(--card-border)}
.contribution-stat span{display:block;color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
.contribution-stat b{display:block;color:var(--text);font-size:1rem;line-height:1.35;overflow-wrap:anywhere}
@keyframes blink{0%,45%{opacity:1}46%,100%{opacity:0}}
@keyframes sponsorWobble{0%,100%{transform:translate(0,0) rotate(0)}25%{transform:translate(-1px,-2px) rotate(-.8deg)}50%{transform:translate(0,-2.5px) rotate(0)}75%{transform:translate(1px,-2px) rotate(.8deg)}}
@media (prefers-reduced-motion:reduce){
  .cursor,.tagline{animation:none}
  .share-trigger,.share-close,.share-action,.card,.tool-row{transition:none}
}
@media (min-width:781px){
  .rank-head,.rank-line,.tools-head,.tool-row{display:grid;grid-template-columns:20px minmax(0,1fr) 72px 100px 100px;gap:16px;align-items:center}
  .tools-head>:nth-child(1),.tool-row>:nth-child(1){grid-column:2}
  :not(.rank-head)+.rank-list>.rank-line:first-child{margin-top:28px}
  :not(.rank-head)+.rank-list>.rank-line:first-child>.pct::before,:not(.rank-head)+.rank-list>.rank-line:first-child>.tokens::before,:not(.rank-head)+.rank-list>.rank-line:first-child>.cost::before{content:attr(data-label);position:absolute;bottom:100%;right:0;margin-bottom:12px;font-size:.72rem;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.08em;pointer-events:none;white-space:nowrap}
}
@media (max-width:780px){
  .wrap{padding:32px 16px}
  header{display:block}
  .meta{text-align:left;margin-top:16px}
  .header-actions{align-items:flex-start;justify-self:start;min-width:0;margin-top:16px}
  .date-filter{align-items:flex-start}
  .date-inputs{width:100%}
  .rank-head,.tools-head{display:none}
  .rank-list{display:grid;gap:12px}
  .rank-line{display:grid;grid-template-columns:1fr;gap:8px;padding:12px;border:none;border-bottom:1px solid var(--card-border);border-radius:0;background:transparent;box-shadow:none}
  .rank-line .arrow{display:none}
  .rank-line.model-group .arrow,.rank-line[data-project-index] .arrow{display:inline}
  .rank-line .name,.rank-line .model-name{white-space:normal;font-weight:700;color:var(--text)}
  .rank-line .pct,.rank-line .tokens,.rank-line .cost,.tool-row .pct,.tool-row .tokens,.tool-row .cost{display:flex;justify-content:space-between;gap:14px;text-align:left}
  .rank-line .pct::before,.rank-line .tokens::before,.rank-line .cost::before,.tool-row .pct::before,.tool-row .tokens::before,.tool-row .cost::before{content:attr(data-label);color:var(--muted);font-weight:500}
  .cards{grid-template-columns:repeat(2,minmax(0,1fr))}
  .cards:has([data-card]){grid-template-columns:repeat(2,minmax(0,1fr))}
  .cards:has([data-card]) .card:nth-child(odd){border-left:0}
  .cards:has([data-card]) .card:nth-child(n+3){border-top:1px solid var(--card-border)}
  .card:nth-child(3){border-left:0}
  .card:nth-child(n+3){border-top:1px solid var(--card-border)}
  .trend-row{grid-template-columns:minmax(0,1fr) 72px 80px;gap:12px;padding:12px}
  .one-pass-row{grid-template-columns:minmax(0,1fr) 104px 56px;gap:10px}
  .tool-row{grid-template-columns:1fr;gap:8px}
  .tool-row .pct:empty,.tool-row .tokens:empty,.tool-row .cost:empty{display:none}
  .wrapped-card{grid-template-columns:minmax(0,1fr) 140px;gap:20px}
  .wrapped-art img{width:140px}
  .wrapped-metrics{grid-template-columns:minmax(0,1fr);gap:0;padding-top:8px}
  .wrapped-metric{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;padding:12px 0;border-bottom:1px solid var(--faint)}
  .wrapped-metric:last-child{border-bottom:0}
  .wrapped-metric span{margin:0}
  .wrapped-metric b{text-align:right}
  .contribution-months{padding-left:30px}
}
@media (max-width:480px){
  .wrap{padding:24px 12px 32px}
  h1{white-space:normal}
  .cards{grid-template-columns:minmax(0,1fr);gap:0}
  .cards:has([data-card]){grid-template-columns:minmax(0,1fr)}
  .cards:not(:has(.card:nth-child(4))){grid-template-columns:minmax(0,1fr)}
  .card{padding:16px;grid-template-columns:minmax(0,1fr) auto;grid-template-rows:auto auto;gap:4px 12px;align-items:baseline}
  .card+.card{border-left:0;border-top:1px solid var(--card-border)}
  .card span{padding:0;letter-spacing:0}
  .card b{text-align:right;font-size:1.2rem}
  .card i{grid-column:1/-1;padding-top:4px}
  .wrapped-card{grid-template-columns:minmax(0,1fr)}
  .wrapped-art{justify-items:start}
  .persona-hours{gap:2px;grid-template-columns:repeat(24,minmax(0,1fr))}
  .share-dialog{width:100%;max-width:none;height:100dvh;max-height:none;margin:0;border:0;border-radius:0}
  .share-modal{min-height:100dvh;padding:20px 16px}
  .share-section{padding:14px}
  .share-action{min-height:42px;font-size:.72rem;gap:6px;white-space:normal}
  .share-file-actions{grid-template-columns:1fr}
  .section{padding:20px 16px}
  .trend-row{grid-template-columns:minmax(0,1fr) 64px 72px;gap:8px;padding:12px 8px}
  .trend-row .week,.trend-row em,.delta{font-size:.74rem}
  .trend-summary{font-size:.8rem}
  .wrapped-metrics,.contribution-stats{grid-template-columns:1fr}
  .contribution-months{font-size:.66rem;padding-left:26px}
  .contribution-board{grid-template-columns:22px minmax(0,1fr)}
  .contribution-days{font-size:.58rem}
}
@media print{
  :root{--bg:#fff;--panel:#fff;--card-bg:#fff;--soft:#fff;--text:#1f2318;--text-soft:#34382b;--muted:#555b49;--token:#6b5318;--cost:#256b59;--warn:#8c4624;--accent-purple:#514a7a}
  body{background:#fff!important;color:#1f2318!important}
  .section,.card,.wrapped,.wrapped-section,.wrapped-card,.trend-row,.rank-line{break-inside:avoid}
  .share-trigger,.share-dialog,.date-filter{display:none!important}
  .card,.rank-line,.trend-row,.tool-row,.share-trigger,.share-close,.share-action,.sponsor a{box-shadow:none!important;transform:none!important}
}""")
