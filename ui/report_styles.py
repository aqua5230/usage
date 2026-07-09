"""CSS for the HTML usage report. Extracted verbatim from html_report."""

REPORT_CSS = """:root{
  --bg:#0b0908;
  --bg-gradient-1:rgba(224,154,88,.14);
  --bg-gradient-2:rgba(90,191,160,.12);
  --panel:rgba(23,19,14,.45);
  --card-bg:rgba(23,19,14,.55);
  --card-border:rgba(255,255,255,.08);
  --card-shadow:rgba(0,0,0,.4);
  --soft:rgba(34,28,20,.45);
  --text:#f5f2ec;
  --text-soft:#ddd6c8;
  --muted:#a39a8a;
  --faint:rgba(255,255,255,.08);
  --token:#e8c66a;
  --cost:#5abfa0;
  --warn:#e0885a;
  --accent-purple:#df9a58;
  --noise-img:url("data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgMjAwIDIwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KICA8ZmlsdGVyIGlkPSJub2lzZSI+CiAgICA8ZmVUdXJidWxlbmNlIHR5cGU9ImZyYWN0YWxOb2lzZSIgYmFzZUZyZXF1ZW5jeT0iMC44NSIgbnVtT2N0YXZlcz0iNCIgc3RpdGNoVGlsZXM9InN0aXRjaCIvPgogIDwvZmlsdGVyPgogIDxyZWN0IHdpZHRoPSIxMDAlIiBoZWlnaHQ9IjEwMCUiIGZpbHRlcj0idXJsKCNub2lzZSkiIG9wYWNpdHk9IjAuMDQiLz4KPC9zdmc+");
  --glass-blur:12px;
  --contrib-0:rgba(255,255,255,.05);
  --contrib-1:rgba(227,197,101,.25);
  --contrib-2:rgba(227,197,101,.45);
  --contrib-3:rgba(227,197,101,.7);
  --contrib-4:rgba(227,197,101,.95);
}

@media (prefers-color-scheme: light){
  :root{
    --bg:#f6f2e9;
    --bg-gradient-1:rgba(161,130,31,.08);
    --bg-gradient-2:rgba(46,125,104,.08);
    --panel:rgba(255,253,246,.55);
    --card-bg:rgba(255,253,246,.68);
    --card-border:rgba(255,255,255,.45);
    --card-shadow:rgba(31,41,55,.06);
    --soft:rgba(240,234,220,.7);
    --text:#292317;
    --text-soft:#43392a;
    --muted:#6b6151;
    --faint:rgba(0,0,0,.06);
    --token:#8a6a1c;
    --cost:#2e7d68;
    --warn:#b05a2b;
    --accent-purple:#a1621f;
    --noise-img:url("data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgMjAwIDIwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KICA8ZmlsdGVyIGlkPSJub2lzZSI+CiAgICA8ZmVUdXJidWxlbmNlIHR5cGU9ImZyYWN0YWxOb2lzZSIgYmFzZUZyZXF1ZW5jeT0iMC44NSIgbnVtT2N0YXZlcz0iNCIgc3RpdGNoVGlsZXM9InN0aXRjaCIvPgogIDwvZmlsdGVyPgogIDxyZWN0IHdpZHRoPSIxMDAlIiBoZWlnaHQ9IjEwMCUiIGZpbHRlcj0idXJsKCNub2lzZSkiIG9wYWNpdHk9IjAuMDE4Ii8+Cjwvc3ZnPg==");
    --glass-blur:16px;
    --contrib-0:rgba(0,0,0,.05);
    --contrib-1:rgba(161,130,31,.25);
    --contrib-2:rgba(161,130,31,.45);
    --contrib-3:rgba(161,130,31,.7);
    --contrib-4:rgba(161,130,31,.95);
  }
}

html{font-size:17.5px}
*{box-sizing:border-box}
body{
  margin:0;
  background-color:var(--bg);
  background-image:var(--noise-img),radial-gradient(circle at 15% 20%,var(--bg-gradient-1) 0%,transparent 45%),radial-gradient(circle at 85% 75%,var(--bg-gradient-2) 0%,transparent 45%),radial-gradient(circle at 50% 50%,rgba(99,102,241,.05) 0%,transparent 50%);
  background-attachment:fixed;
  background-size:auto,100% 100%,100% 100%,100% 100%;
  color:var(--text);
  font-family:"Styrene A","Styrene B","Helvetica Neue",system-ui,sans-serif;
  line-height:1.55;
  -webkit-font-smoothing:antialiased;
  -moz-osx-font-smoothing:grayscale;
}
.wrap{max-width:960px;margin:0 auto;padding:48px 24px}
header{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:28px;align-items:start;margin-bottom:32px}
h1,.wrapped-copy h3,.wrapped-total,.prompt,.share-modal h2,.share-section h3,.persona-card h3,.ai-update-head h3{
  font-family:"Grenette",Georgia,serif;
}
h1{
  margin:0 0 12px;
  font-size:clamp(2rem,5vw,3.2rem);
  line-height:1.05;
  font-weight:800;
  letter-spacing:-.03em;
  white-space:nowrap;
  background:linear-gradient(135deg,#fff 40%,var(--token) 90%,var(--accent-purple) 100%);
  -webkit-background-clip:text;
  -webkit-text-fill-color:transparent;
}
@media (prefers-color-scheme: light){
  h1{
    background:linear-gradient(135deg,var(--text) 50%,var(--token) 100%);
    -webkit-background-clip:text;
    -webkit-text-fill-color:transparent;
  }
}
.eyebrow,.meta,.empty,footer,.cursor,.prompt,.share-trigger,.share-close,.share-action,.tokens,.cost,.pct,.trend-row .week,.trend-row b,.trend-row em,.delta,.donut-total,.donut-sub,.sub-plan,.sub-since,.ai-update-version,.ai-update-period,th,td,.wrapped-kicker,.wrapped-total-label,.contribution-months,.contribution-days,.contribution-legend{
  font-family:ui-monospace,SFMono-Regular,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
}
.eyebrow,.meta,.empty,footer{color:var(--muted)}
.eyebrow span,.prompt span,.cursor{color:var(--token)}
.cursor{display:inline-block;animation:blink 1.2s steps(2,start) infinite}
.narrative{max-width:760px;margin:18px 0 0;color:var(--text-soft);font-size:1.02rem;line-height:1.6}
.meta{font-size:.82rem;text-align:right;white-space:nowrap;line-height:1.4}
.header-actions{display:flex;flex-direction:column;align-items:flex-end;gap:12px}
.share-trigger{
  display:inline-flex;align-items:center;gap:8px;background:rgba(255,255,255,.06);border:1px solid var(--card-border);color:var(--text);padding:6px 14px;border-radius:8px;cursor:pointer;font-size:.8rem;font-weight:500;line-height:1.3;text-decoration:none;transition:all .2s ease;backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)
}
.share-trigger:hover{border-color:var(--token);color:var(--token);background:rgba(255,255,255,.12);transform:translateY(-2px);box-shadow:0 4px 12px rgba(232,198,106,.15)}
@media (prefers-color-scheme: light){
  .share-trigger{background:rgba(0,0,0,.04)}
  .share-trigger:hover{background:rgba(0,0,0,.08)}
}
.share-trigger:focus-visible,.share-close:focus-visible,.share-action:focus-visible{outline:2px solid var(--token);outline-offset:2px}
.cards{display:grid;grid-template-columns:1.7fr 1.15fr .95fr .95fr .95fr .95fr;gap:12px;margin:24px 0 16px}
.card{
  background:var(--card-bg);padding:18px 16px;border-radius:12px;min-height:112px;display:flex;flex-direction:column;backdrop-filter:blur(var(--glass-blur));-webkit-backdrop-filter:blur(var(--glass-blur));border:1px solid var(--card-border);box-shadow:0 8px 32px 0 var(--card-shadow);transition:all .25s cubic-bezier(.4,0,.2,1)
}
.card:hover{transform:translateY(-4px);border-color:rgba(232,198,106,.35);box-shadow:0 12px 40px 0 rgba(232,198,106,.15)}
.card span{display:block;color:var(--muted);font-size:.82rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
.card b{display:block;font-size:clamp(1.5rem,2vw,1.9rem);color:var(--text);white-space:nowrap;overflow-wrap:normal;line-height:1.2;font-weight:700;letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.card i{display:block;font-style:normal;color:var(--muted);font-size:.8rem;margin-top:auto;padding-top:6px;overflow-wrap:anywhere;letter-spacing:0}
.card:first-child b{color:var(--token);text-shadow:0 0 12px rgba(232,198,106,.25)}
.card:nth-child(2) b{color:var(--cost);text-shadow:0 0 12px rgba(90,191,160,.25)}
@media (prefers-color-scheme: light){
  .card:first-child b,.card:nth-child(2) b{text-shadow:none}
}
.section{
  background:var(--panel);border-radius:12px;margin-top:20px;padding:24px 20px;backdrop-filter:blur(var(--glass-blur));-webkit-backdrop-filter:blur(var(--glass-blur));border:1px solid var(--card-border);box-shadow:0 8px 32px 0 var(--card-shadow)
}
.prompt{font-size:.95rem;color:var(--text);margin-bottom:6px;font-weight:600;display:flex;align-items:center;gap:8px}
.rule{font-size:0;height:1px;background:linear-gradient(90deg,var(--card-border),transparent);margin-bottom:16px;border:none}
.rank-head,.rank-line{display:grid;grid-template-columns:24px minmax(0,1fr) 72px 92px 88px;gap:12px;align-items:center}
.rank-head{color:var(--muted);font-size:.74rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px}
.rank-head>span:nth-child(n+3){text-align:right}
.rank-line{padding:10px 0;color:var(--text-soft);border-bottom:1px solid rgba(255,255,255,.03)}
@media (prefers-color-scheme: light){
  .rank-line{border-bottom:1px solid rgba(0,0,0,.03)}
}
.rank-line:last-child{border-bottom:none}
.arrow{color:var(--warn)}
.name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pct{color:var(--token)}
.cost{color:var(--cost)}
.tokens,.cost,.pct{text-align:right;white-space:nowrap}
.trend{display:grid;gap:10px}
.trend-row{display:grid;grid-template-columns:58px minmax(0,1fr) 72px 82px;gap:12px;align-items:center}
.trend-row .week{color:var(--muted)}
.trend-row b{font-weight:400;white-space:nowrap;overflow:hidden;display:block;color:var(--token)}
.trend-row em{font-style:normal;text-align:right;color:var(--text-soft)}
.delta{color:var(--muted);white-space:nowrap}
.delta.up{color:var(--cost)}
.delta.down{color:var(--warn)}
.delta.flat{color:var(--muted)}
.trend-summary{color:var(--text-soft);margin-top:10px;font-size:.9rem}
.insight-note,.insight-action{padding:12px 16px;border-radius:8px;margin-bottom:10px;font-size:.9rem;line-height:1.5}
.insight-note{background:rgba(232,198,106,.06);border-left:3px solid var(--token);color:var(--text-soft)}
.insight-action{background:rgba(224,136,90,.06);border-left:3px solid var(--warn);color:var(--text-soft);margin-bottom:0}
.persona-card{border:1px solid var(--card-border);border-radius:12px;background:var(--soft);padding:18px;min-width:0}
.persona-card h3{margin:0 0 14px;color:var(--text);font-size:.95rem;font-weight:700}
.persona-caption{margin:0 0 16px;color:var(--text-soft);font-size:.88rem;line-height:1.5}
.persona-hours{display:grid;grid-template-columns:repeat(24,minmax(8px,1fr));gap:4px;align-items:end;height:176px;padding-top:8px}
.persona-hour{display:grid;grid-template-rows:1fr auto;gap:7px;align-items:end;min-width:0;height:100%}
.persona-hour span{display:block;width:100%;min-height:1.5px;border-radius:4px 4px 1px 1px;background:linear-gradient(180deg,var(--token),var(--accent-purple))}
.persona-hour.is-peak span{background:linear-gradient(180deg,var(--cost),var(--token));box-shadow:0 0 12px rgba(90,191,160,.4)}
.persona-hour em{font-style:normal;color:var(--muted);font-size:.58rem;text-align:center;overflow:hidden}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:760px}
th,td{padding:12px 16px;text-align:left;font-size:.95rem}
th{color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--card-border)}
td{color:var(--text-soft);border-bottom:1px solid rgba(255,255,255,.03)}
@media (prefers-color-scheme: light){
  td{border-bottom:1px solid rgba(0,0,0,.03)}
}
td:first-child{color:var(--warn)}
.share-dialog{
  width:min(760px,calc(100vw - 28px));max-height:min(92vh,860px);border:1px solid var(--card-border);border-radius:12px;background:var(--panel);color:var(--text);padding:0;box-shadow:0 24px 70px rgba(0,0,0,.6);overflow:auto;backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px)
}
.share-dialog::backdrop{background:rgba(5,7,10,.72);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)}
@media (prefers-color-scheme: light){
  .share-dialog::backdrop{background:rgba(243,244,246,.72)}
}
.share-modal{position:relative;padding:24px;display:grid;gap:18px;align-content:start}
.share-modal h2{margin:0 40px 0 0;font-size:1.15rem;line-height:1.35;letter-spacing:0;font-weight:700}
.share-close{
  position:absolute;top:16px;right:16px;width:32px;height:32px;display:grid;place-items:center;border:1px solid var(--card-border);border-radius:8px;background:rgba(255,255,255,.06);color:var(--text);cursor:pointer;font-size:1.1rem;line-height:1;transition:all .2s ease
}
.share-close:hover{border-color:var(--token);color:var(--token);background:rgba(255,255,255,.12)}
.share-section{border:1px solid var(--card-border);border-radius:10px;background:var(--soft);padding:16px;display:grid;gap:14px}
.share-section h3{margin:0;color:var(--text);font-size:.98rem;line-height:1.35;letter-spacing:0;font-weight:700}
.share-file-mask{display:inline-flex;align-items:center;gap:9px;color:var(--text-soft);font-size:.86rem;cursor:pointer;user-select:none}
.share-file-mask input{width:16px;height:16px;accent-color:var(--token)}
.share-action{
  display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:38px;border:1px solid var(--card-border);border-radius:8px;background:rgba(255,255,255,.06);color:var(--text);cursor:pointer;font-size:.78rem;line-height:1.2;white-space:nowrap;transition:all .2s ease
}
.share-action:hover{border-color:var(--token);color:var(--token);background:rgba(255,255,255,.12);transform:translateY(-1px)}
.share-icon{color:var(--token);font-weight:800}
.share-file-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.share-file-hint{margin:0;color:var(--muted);font-size:.8rem;line-height:1.5}
.share-toast{min-height:20px;color:var(--cost);font-size:.82rem;opacity:0;transition:opacity .2s ease}
.share-toast.show{opacity:1}
.sponsor{display:flex;justify-content:center;align-items:center;gap:18px;flex-wrap:wrap;padding:32px 16px 24px;color:var(--muted);font-size:.88rem}
.sponsor a{opacity:.8;transition:all .2s ease;display:inline-flex;text-decoration:none}
.sponsor a:hover{opacity:1;transform:scale(1.08)}
.sponsor img{vertical-align:middle;display:block}
.tagline{font-size:1rem;color:var(--text-soft);letter-spacing:.01em;animation:sponsorWobble 2.6s ease-in-out infinite;display:inline-block;transform-origin:center center}
.sponsor-link{text-align:center;padding:0 16px 32px;font-size:.8rem}
.sponsor-link a{color:var(--muted);text-decoration:none;opacity:.7;transition:all .2s ease}
.sponsor-link a:hover{opacity:1;color:var(--token)}
.donut-wrap{display:flex;align-items:center;gap:32px;flex-wrap:wrap;margin-bottom:20px}
.donut{width:150px;height:150px;flex:0 0 auto}
.donut circle{transition:stroke-dashoffset .3s ease}
.donut-total{fill:var(--text);font-size:20px;font-weight:700}
.donut-sub{fill:var(--muted);font-size:11px;text-transform:uppercase}
.donut-legend{list-style:none;margin:0;padding:0;display:grid;gap:10px;flex:1 1 200px;min-width:200px}
.donut-legend li{display:grid;grid-template-columns:12px minmax(0,1fr) auto;gap:12px;align-items:center;font-size:.86rem;color:var(--text-soft)}
.donut-legend .dot{width:10px;height:10px;border-radius:3px}
.donut-legend .lg-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.donut-legend .lg-pct{color:var(--muted);text-align:right;font-weight:600}
.tools{display:grid;gap:12px}
.tools-head,.tool-row{display:grid;grid-template-columns:minmax(0,1fr) 72px 100px 100px;gap:18px;align-items:center}
.tools-head{padding:0 16px;color:var(--muted);font-size:.74rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:-2px}
.tools-head>span:nth-child(n+2){text-align:right}
.tool-row{padding:16px;border:1px solid var(--card-border);border-radius:12px;background:var(--soft);transition:all .25s cubic-bezier(.4,0,.2,1)}
.tool-row:hover{transform:translateY(-2px);border-color:rgba(232,198,106,.35);box-shadow:0 8px 24px rgba(232,198,106,.12)}
.tool-head{display:flex;align-items:center;gap:14px;flex-wrap:wrap;min-width:0}
.sub-agent{font-weight:700;color:var(--text)}
.sub-plan{color:var(--token);background:rgba(232,198,106,.12);padding:3px 11px;border-radius:999px;font-size:.82rem;font-weight:600;border:1px solid rgba(232,198,106,.2)}
@media (prefers-color-scheme: light){
  .sub-plan{background:rgba(138,106,28,.08);border:1px solid rgba(138,106,28,.2)}
}
.sub-since{color:var(--muted);font-size:.82rem}
.tool-row .pct,.tool-row .tokens,.tool-row .cost{white-space:nowrap;text-align:right}
.tool-row .pct{color:var(--token);font-weight:600}
.tool-row .tokens{color:var(--text-soft)}
.tool-row .cost{color:var(--cost);font-weight:600}
.ai-updates-grid{display:grid;gap:16px}
.ai-update-card{padding:18px;border:1px solid var(--card-border);border-radius:12px;background:var(--soft)}
.ai-update-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.ai-update-head h3{margin:0;color:var(--text);font-size:1.05rem;line-height:1.35;font-weight:700}
.ai-update-version{color:var(--token);font-size:.84rem;font-weight:600;white-space:nowrap}
.ai-update-period{margin:8px 0 0;color:var(--muted);font-size:.82rem}
.ai-update-items{list-style:none;display:grid;gap:14px;margin:16px 0 0;padding:0;counter-reset:ai-updates}
.ai-update-item{position:relative;counter-increment:ai-updates;padding:16px 16px 14px 48px;border:1px solid var(--card-border);border-radius:10px;background:rgba(0,0,0,.2);box-shadow:inset 0 1px 0 rgba(255,255,255,.03)}
@media (prefers-color-scheme: light){
  .ai-update-item{background:rgba(255,255,255,.4);box-shadow:inset 0 1px 0 rgba(255,255,255,.5)}
}
.ai-update-item:nth-child(even){background:rgba(0,0,0,.1)}
@media (prefers-color-scheme: light){
  .ai-update-item:nth-child(even){background:rgba(255,255,255,.2)}
}
.ai-update-item::before{content:counter(ai-updates,decimal-leading-zero);position:absolute;top:16px;left:16px;color:var(--token);font-size:.72rem;font-weight:700;letter-spacing:.08em;line-height:1}
.ai-update-item-title{margin:0;color:var(--text);font-size:.92rem;font-weight:700;line-height:1.5}
.ai-update-item-body{margin:6px 0 0;color:var(--text-soft);font-size:.9rem;line-height:1.65}
.ai-update-original,.ai-update-history{margin-top:10px;border:1px solid var(--card-border);border-radius:8px;background:rgba(0,0,0,.15)}
@media (prefers-color-scheme: light){
  .ai-update-original,.ai-update-history{background:rgba(255,255,255,.35)}
}
.ai-update-original summary,.ai-update-history summary{cursor:pointer;list-style:none;padding:8px 12px;color:var(--token);font-size:.82rem;font-weight:600;user-select:none;display:flex;align-items:center;gap:6px}
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
.wrapped-section{background:linear-gradient(135deg,rgba(224,154,88,.16),rgba(90,191,160,.13))!important;border:1px solid rgba(255,255,255,.15)!important}
@media (prefers-color-scheme: light){
  .wrapped-section{background:linear-gradient(135deg,rgba(161,130,31,.10),rgba(46,125,104,.08))!important;border:1px solid rgba(255,255,255,.5)!important}
}
.wrapped-card{display:grid;grid-template-columns:minmax(0,1.25fr) 180px minmax(280px,.95fr);gap:20px;align-items:center;padding:4px}
.wrapped-kicker{display:inline-flex;align-items:center;gap:8px;padding:5px 12px;border:1px solid rgba(232,198,106,.3)!important;border-radius:999px;background:rgba(232,198,106,.1)!important;color:var(--token)!important;font-size:.78rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase}
.wrapped-copy h3{margin:16px 0 8px;font-size:clamp(2.2rem,4vw,3.2rem);line-height:.98;letter-spacing:-.03em;font-weight:800;color:var(--text)}
.wrapped-beast-line{margin:0;color:var(--warn);font-size:.95rem;line-height:1.5}
.wrapped-total{margin-top:18px;font-size:3.4rem;line-height:1;font-weight:800;letter-spacing:-.04em;color:var(--text);white-space:nowrap}
.wrapped-total-label{margin:8px 0 0;color:var(--muted);font-size:.9rem;text-transform:uppercase;letter-spacing:.08em}
.wrapped-analogy{margin:10px 0 0;color:var(--text-soft);font-size:.96rem;line-height:1.55}
.wrapped-art{display:grid;place-items:center}
.wrapped-art img{width:min(180px,100%);height:auto;image-rendering:auto;filter:drop-shadow(0 14px 28px rgba(0,0,0,.42)) drop-shadow(0 0 22px rgba(232,198,106,.4))}
@media (prefers-color-scheme: light){
  .wrapped-art img{filter:drop-shadow(0 10px 20px rgba(60,45,20,.25)) invert(1) opacity(.8)}
}
.wrapped-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.wrapped-metric{padding:14px;border:1px solid var(--card-border)!important;border-radius:12px;background:var(--soft)!important;min-width:0}
.wrapped-metric span{display:block;color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
.wrapped-metric b{display:block;color:var(--text);font-size:1rem;line-height:1.35;overflow-wrap:anywhere}
.contribution-wrap{display:grid;gap:16px;align-items:start}
.contribution-heatmap{min-width:0}
.contribution-months{display:grid;grid-template-columns:repeat(var(--weeks),minmax(0,1fr));gap:3px;padding-left:30px;margin-bottom:8px;color:var(--muted);font-size:.7rem;letter-spacing:.01em}
.contribution-months span{min-height:1em;white-space:nowrap;overflow:visible}
.contribution-board{display:grid;grid-template-columns:24px minmax(0,1fr);gap:6px;align-items:stretch}
.contribution-days{display:grid;grid-template-rows:repeat(7,1fr);gap:3px;color:var(--muted);font-size:.6rem;line-height:1;padding-top:0}
.contribution-grid{display:grid;grid-template-columns:repeat(var(--weeks),minmax(0,1fr));grid-template-rows:repeat(7,auto);grid-auto-flow:column;gap:3px}
.contribution-cell{display:block;width:100%;aspect-ratio:1;border-radius:2px;background:var(--contrib-0);border:1px solid var(--card-border)}
.contribution-cell.level-1{background:var(--contrib-1)}
.contribution-cell.level-2{background:var(--contrib-2)}
.contribution-cell.level-3{background:var(--contrib-3)}
.contribution-cell.level-4{background:var(--contrib-4)}
.contribution-legend{display:flex;justify-content:flex-end;align-items:center;gap:6px;margin-top:12px;color:var(--muted);font-size:.72rem}
.contribution-legend .contribution-cell{width:12px;min-width:12px;height:12px;aspect-ratio:auto}
.contribution-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.contribution-stat{padding:14px;border:1px solid var(--card-border);border-radius:12px;background:var(--soft)}
.contribution-stat span{display:block;color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
.contribution-stat b{display:block;color:var(--text);font-size:1rem;line-height:1.35;overflow-wrap:anywhere}
.donut circle:nth-of-type(1),.donut-legend li:nth-of-type(1) .dot{stroke:var(--token)!important;background:var(--token)!important}
.donut circle:nth-of-type(2),.donut-legend li:nth-of-type(2) .dot{stroke:var(--accent-purple)!important;background:var(--accent-purple)!important}
.donut circle:nth-of-type(3),.donut-legend li:nth-of-type(3) .dot{stroke:var(--warn)!important;background:var(--warn)!important}
@keyframes blink{0%,45%{opacity:1}46%,100%{opacity:0}}
@keyframes sponsorWobble{0%,100%{transform:translate(0,0) rotate(0)}25%{transform:translate(-1px,-2px) rotate(-.8deg)}50%{transform:translate(0,-2.5px) rotate(0)}75%{transform:translate(1px,-2px) rotate(.8deg)}}
@media (max-width:780px){
  .wrap{padding:32px 16px}
  header{display:block}
  .meta{text-align:left;margin-top:16px}
  .header-actions{align-items:flex-start;margin-top:16px}
  .cards{grid-template-columns:repeat(2,1fr)}
  .rank-head,.tools-head{display:none}
  .rank-list{display:grid;gap:12px}
  .rank-line{display:grid;grid-template-columns:1fr;gap:8px;padding:16px;border:1px solid var(--card-border);border-radius:10px;background:var(--soft)}
  .rank-line .arrow{display:none}
  .rank-line .name{white-space:normal;font-weight:700;color:var(--text)}
  .rank-line .pct,.rank-line .tokens,.rank-line .cost,.tool-row .pct,.tool-row .tokens,.tool-row .cost{display:flex;justify-content:space-between;gap:14px;text-align:left}
  .rank-line .pct::before,.rank-line .tokens::before,.rank-line .cost::before,.tool-row .pct::before,.tool-row .tokens::before,.tool-row .cost::before{content:attr(data-label);color:var(--muted);font-weight:500}
  .tool-row{grid-template-columns:1fr;gap:8px}
  .tool-row .pct:empty,.tool-row .tokens:empty,.tool-row .cost:empty{display:none}
  .wrapped-card{grid-template-columns:1fr;gap:16px}
  .wrapped-art{order:-1}
  .wrapped-art img{width:140px}
  .wrapped-metrics{grid-template-columns:1fr 1fr}
  .contribution-months{padding-left:30px}
}
@media (max-width:480px){
  .wrap{padding:24px 12px 32px}
  h1{white-space:normal}
  .cards{grid-template-columns:repeat(2,1fr);gap:10px}
  .card{min-height:100px;padding:14px 12px}
  .share-dialog{width:100vw;max-width:none;height:100dvh;max-height:none;margin:0;border:0;border-radius:0}
  .share-modal{min-height:100dvh;padding:20px 16px}
  .share-section{padding:14px}
  .share-action{min-height:42px;font-size:.72rem;gap:6px;white-space:normal}
  .share-file-actions{grid-template-columns:1fr}
  .section{padding:20px 16px}
  .wrapped-metrics,.contribution-stats{grid-template-columns:1fr}
  .contribution-months{font-size:.66rem;padding-left:26px}
  .contribution-board{grid-template-columns:22px minmax(0,1fr)}
  .contribution-days{font-size:.58rem}
}"""
