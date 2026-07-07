"""CSS for the HTML usage report. Extracted verbatim from html_report."""

REPORT_CSS = """:root{--bg:#050505;--panel:#0d0f12;--soft:#15181d;--text:#f2f4f8;--muted:#8b949e;--faint:#343941;--token:#58a6ff;--cost:#3fb950;--warn:#d29922;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;line-height:1.55}
.wrap{max-width:960px;margin:0 auto;padding:42px 22px 34px}
header{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:28px;align-items:start;margin-bottom:26px}
h1{margin:0 0 10px;font-size:clamp(1.8rem, 4.2vw, 3rem);line-height:1.02;font-weight:800;letter-spacing:-0.02em;white-space:nowrap}
.eyebrow,.meta,.empty,footer{color:var(--muted)}
.eyebrow span,.prompt span,.cursor{color:var(--token)}
.cursor{display:inline-block;animation:blink 1s steps(2,start) infinite}
.narrative{max-width:760px;margin:18px 0 0;color:#d5dbe4;font-size:1.02rem}
.meta{font-size:.82rem;text-align:right;white-space:nowrap}
.header-actions{display:flex;flex-direction:column;align-items:flex-end;gap:10px}
.share-trigger{display:inline-flex;align-items:center;gap:7px;background:#161b22;border:1px solid #30363d;color:#f0f6fc;padding:4px 11px;border-radius:4px;cursor:pointer;font:inherit;font-size:.8rem;line-height:1.3;text-decoration:none;transition:border-color .15s,color .15s,transform .15s}
.share-trigger:hover{border-color:#58a6ff;color:#58a6ff;transform:translateY(-1px)}
.share-trigger:focus-visible,.share-close:focus-visible,.share-action:focus-visible{outline:2px solid #58a6ff;outline-offset:2px}
.cards{display:grid;grid-template-columns:1.7fr 1.15fr .95fr .95fr .95fr .95fr;gap:10px;margin:22px 0 12px}
.card{background:var(--panel);padding:16px 14px;border-radius:6px;min-height:108px;display:flex;flex-direction:column}
.card span{display:block;color:var(--muted);font-size:.75rem;text-transform:uppercase;margin-bottom:10px}
.card b{display:block;font-size:clamp(1rem,1.5vw,1.3rem);color:var(--text);white-space:nowrap;overflow-wrap:normal;line-height:1.2;font-weight:700;letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.card i{display:block;font-style:normal;color:var(--muted);font-size:.72rem;margin-top:auto;padding-top:6px;overflow-wrap:anywhere;letter-spacing:0}
.card:first-child b{color:var(--token)}.card:nth-child(2) b{color:var(--cost)}
.section{background:var(--panel);border-radius:8px;margin-top:16px;padding:18px 16px}
.prompt{font-size:.95rem;color:#f0f6fc;margin-bottom:4px}
.rule{color:var(--faint);white-space:nowrap;overflow:hidden;margin-bottom:14px}
.rank-head,.rank-line{display:grid;grid-template-columns:24px minmax(0,1fr) 72px 92px 88px;gap:12px;align-items:center}
.rank-head{color:var(--muted);font-size:.74rem;text-transform:uppercase;margin-bottom:8px}
.rank-head>span:nth-child(n+3){text-align:right}
.rank-line{padding:7px 0;color:#dce2ea}
.arrow{color:var(--warn)}.name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pct{color:var(--token)}.cost{color:var(--cost)}.tokens,.cost,.pct{text-align:right;white-space:nowrap}
.trend{display:grid;gap:6px}
.trend-row{display:grid;grid-template-columns:58px minmax(0,1fr) 72px 82px;gap:12px;align-items:center}
.trend-row .week{color:var(--muted)}.trend-row b{color:var(--token);font-weight:400;white-space:nowrap;overflow:hidden}.trend-row em{font-style:normal;text-align:right;color:#dce2ea}.delta{color:var(--muted);white-space:nowrap}.delta.up{color:var(--cost)}.delta.down{color:var(--warn)}.delta.flat{color:var(--muted)}.trend-summary{color:#dce2ea;margin-top:8px}
.persona-card{border:1px solid #30363d;border-radius:7px;background:#090b0e;padding:14px;min-width:0}
.persona-card h3{margin:0 0 12px;color:#f0f6fc;font-size:.9rem;font-weight:700;letter-spacing:0}
.persona-caption{margin:0 0 14px;color:#dce2ea;font-size:.86rem;line-height:1.5}
.persona-hours{display:grid;grid-template-columns:repeat(24,minmax(8px,1fr));gap:4px;align-items:end;height:176px;padding-top:8px}
.persona-hour{display:grid;grid-template-rows:1fr auto;gap:7px;align-items:end;min-width:0;height:100%}
.persona-hour span{display:block;width:100%;min-height:1px;border-radius:3px 3px 1px 1px;background:linear-gradient(180deg,var(--token),#285f9f)}
.persona-hour.is-peak span{background:linear-gradient(180deg,#56d364,var(--token));box-shadow:0 0 12px rgba(86,211,100,.28)}
.persona-hour em{font-style:normal;color:var(--muted);font-size:.58rem;text-align:center;overflow:hidden}
.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;min-width:760px}th,td{padding:8px 10px;text-align:left;font-size:.86rem}th{color:var(--muted);font-weight:500;text-transform:uppercase}td{color:#dce2ea}td:first-child{color:var(--warn)}
.share-dialog{width:min(760px,calc(100vw - 28px));max-height:min(92vh,860px);border:1px solid #30363d;border-radius:8px;background:#0d0f12;color:var(--text);padding:0;box-shadow:0 24px 70px rgba(0,0,0,.58);overflow:auto}
.share-dialog::backdrop{background:rgba(0,0,0,.72)}
.share-modal{position:relative;padding:20px;display:grid;gap:16px;align-content:start}
.share-modal h2{margin:0 40px 0 0;font-size:1.1rem;line-height:1.35;letter-spacing:0}
.share-close{position:absolute;top:14px;right:14px;width:30px;height:30px;display:grid;place-items:center;border:1px solid #30363d;border-radius:4px;background:#161b22;color:#f0f6fc;cursor:pointer;font:inherit;font-size:1.1rem;line-height:1}
.share-close:hover{border-color:#58a6ff;color:#58a6ff}
.share-section{border:1px solid #30363d;border-radius:8px;background:#090b0e;padding:14px;display:grid;gap:12px}
.share-section h3{margin:0;color:#f0f6fc;font-size:.98rem;line-height:1.35;letter-spacing:0}
.share-file-mask{display:inline-flex;align-items:center;gap:9px;color:#dce2ea;font-size:.86rem;cursor:pointer;user-select:none}
.share-file-mask input{width:16px;height:16px;accent-color:#58a6ff}
.share-action{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:36px;border:1px solid #30363d;border-radius:4px;background:#161b22;color:#f0f6fc;cursor:pointer;font:inherit;font-size:.78rem;line-height:1.2;white-space:nowrap;transition:border-color .15s,color .15s,transform .15s}
.share-action:hover{border-color:#58a6ff;color:#58a6ff;transform:translateY(-1px)}
.share-icon{color:#58a6ff;font-weight:800}
.share-file-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.share-file-hint{margin:0;color:var(--muted);font-size:.8rem;line-height:1.5}
.share-toast{min-height:20px;color:#56d364;font-size:.82rem;opacity:0;transition:opacity .15s}
.share-toast.show{opacity:1}
.sponsor{display:flex;justify-content:center;align-items:center;gap:18px;flex-wrap:wrap;padding:24px 16px 32px;color:var(--muted);font-size:.88rem}
.sponsor a{opacity:.85;transition:opacity .2s,transform .2s;text-decoration:none;display:inline-flex}
.sponsor a:hover{opacity:1;transform:scale(1.06)}
.sponsor img{vertical-align:middle;display:block}
.tagline{font-size:1rem;color:#d5dbe4;letter-spacing:.01em;animation:sponsorWobble 2.6s ease-in-out infinite;display:inline-block;transform-origin:center center}
.sponsor-link{text-align:center;padding:0 16px 24px;font-size:.8rem}
.sponsor-link a{color:var(--muted);text-decoration:none;opacity:.7;transition:opacity .2s}
.sponsor-link a:hover{opacity:1;color:var(--token)}
@keyframes blink{0%,45%{opacity:1}46%,100%{opacity:0}}
@keyframes sponsorWobble{0%,100%{transform:translate(0,0) rotate(0)}25%{transform:translate(-1px,-2px) rotate(-.8deg)}50%{transform:translate(0,-2.5px) rotate(0)}75%{transform:translate(1px,-2px) rotate(.8deg)}}
.trend{display:grid;gap:6px}
.trend-row{display:grid;grid-template-columns:58px minmax(0,1fr) 72px 82px;gap:12px;align-items:center}
.trend-row .week{color:var(--muted)}.trend-row b{color:var(--token);font-weight:400;white-space:nowrap;overflow:hidden}.trend-row em{font-style:normal;text-align:right;color:#dce2ea}.delta{color:var(--muted);white-space:nowrap}.delta.up{color:var(--cost)}.delta.down{color:var(--warn)}.delta.flat{color:var(--muted)}.trend-summary{color:#dce2ea;margin-top:8px}
.donut-wrap{display:flex;align-items:center;gap:24px;flex-wrap:wrap;margin-bottom:18px}
.donut{width:150px;height:150px;flex:0 0 auto}
.donut-total{fill:var(--text);font-size:20px;font-weight:700}
.donut-sub{fill:var(--muted);font-size:11px;text-transform:uppercase}
.donut-legend{list-style:none;margin:0;padding:0;display:grid;gap:8px;flex:1 1 200px;min-width:200px}
.donut-legend li{display:grid;grid-template-columns:12px minmax(0,1fr) auto;gap:10px;align-items:center;font-size:.86rem;color:#dce2ea}
.donut-legend .dot{width:10px;height:10px;border-radius:2px}
.donut-legend .lg-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.donut-legend .lg-pct{color:var(--muted);text-align:right}
.tools{display:grid;gap:10px}
.tools-head,.tool-row{display:grid;grid-template-columns:minmax(0,1fr) 72px 100px 100px;gap:18px;align-items:center}
.tools-head{padding:0 17px;color:var(--muted);font-size:.74rem;text-transform:uppercase;margin-bottom:-2px}
.tools-head>span:nth-child(n+2){text-align:right}
.tool-row{padding:14px 16px;border:1px solid #30363d;border-radius:7px;background:#090b0e}
.tool-head{display:flex;align-items:center;gap:14px;flex-wrap:wrap;min-width:0}
.sub-agent{font-weight:700;color:#f0f6fc}
.sub-plan{color:var(--token);background:rgba(56,139,253,0.12);padding:3px 11px;border-radius:999px;font-size:.86rem}
.sub-since{color:var(--muted);font-size:.84rem}
.tool-row .pct,.tool-row .tokens,.tool-row .cost{white-space:nowrap;text-align:right}
.tool-row .pct{color:var(--token)}.tool-row .tokens{color:#dce2ea}.tool-row .cost{color:var(--cost)}
.ai-updates-grid{display:grid;gap:12px}
.ai-update-card{padding:14px 16px;border:1px solid #30363d;border-radius:7px;background:#090b0e}
.ai-update-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.ai-update-head h3{margin:0;color:#f0f6fc;font-size:1rem;line-height:1.35}
.ai-update-version{color:var(--token);font-size:.84rem;white-space:nowrap}
.ai-update-period{margin:8px 0 0;color:var(--muted);font-size:.82rem}
.ai-update-items{list-style:none;display:grid;gap:14px;margin:14px 0 0;padding:0;counter-reset:ai-updates}
.ai-update-item{position:relative;counter-increment:ai-updates;padding:14px 14px 12px 46px;border:1px solid #20252c;border-radius:8px;background:linear-gradient(180deg,#10141a,#0c1015);box-shadow:inset 0 1px 0 rgba(255,255,255,.03)}
.ai-update-item:nth-child(even){background:linear-gradient(180deg,#111821,#0d1218);border-color:#27303a}
.ai-update-item::before{content:counter(ai-updates, decimal-leading-zero);position:absolute;top:14px;left:14px;color:var(--token);font-size:.72rem;font-weight:700;letter-spacing:.08em;line-height:1}
.ai-update-item-title{margin:0;color:#f0f6fc;font-size:.92rem;font-weight:700;line-height:1.5}
.ai-update-item-body{margin:6px 0 0;color:#dce2ea;font-size:.9rem;line-height:1.65}
.ai-update-original{margin-top:8px;border:1px solid #262c34;border-radius:6px;background:#0d1014}
.ai-update-original summary{cursor:pointer;list-style:none;padding:8px 10px;color:var(--token);font-size:.82rem;user-select:none}
.ai-update-original summary::-webkit-details-marker{display:none}
.ai-update-original[open] summary{border-bottom:1px solid #262c34}
.ai-update-original div{padding:10px;color:var(--muted);font-size:.82rem;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}
.ai-update-history{margin-top:12px;border:1px solid #262c34;border-radius:6px;background:#0d1014}
.ai-update-history summary{cursor:pointer;list-style:none;padding:8px 10px;color:var(--token);font-size:.82rem;user-select:none}
.ai-update-history summary::-webkit-details-marker{display:none}
.ai-update-history[open] summary{border-bottom:1px solid #262c34}
.ai-update-history>div{padding:10px;display:grid;gap:12px}
.ai-update-history-period{padding-left:12px;border-left:2px solid #1f2933}
.ai-update-history-period .ai-update-period{margin:0;color:#9fb3c8;font-size:.78rem}
.ai-update-history-items{list-style:none;display:grid;gap:10px;margin:8px 0 0;padding:0}
.ai-update-history-item{padding:0}
.ai-update-history-item .ai-update-item-title{font-size:.86rem}
.ai-update-history-item .ai-update-item-body{font-size:.84rem;color:#c6d0db}
.wrapped-section{background:linear-gradient(135deg,#11161c,#090c10 58%,#161015)}
.wrapped-card{display:grid;grid-template-columns:minmax(0,1.25fr) 180px minmax(280px,.95fr);gap:18px;align-items:center;padding:4px}
.wrapped-kicker{display:inline-flex;align-items:center;gap:8px;padding:5px 10px;border:1px solid rgba(88,166,255,.28);border-radius:999px;background:rgba(88,166,255,.08);color:#9bc5ff;font-size:.78rem;letter-spacing:.08em;text-transform:uppercase}
.wrapped-copy h3{margin:14px 0 8px;font-size:clamp(1.7rem,3.6vw,2.5rem);line-height:.98;letter-spacing:-.03em}
.wrapped-beast-line{margin:0;color:#f7d38e;font-size:.95rem;line-height:1.5}
.wrapped-total{margin-top:18px;font-size:clamp(1.7rem,4.2vw,2.8rem);line-height:1;font-weight:800;letter-spacing:-.04em;color:#f0f6fc;white-space:nowrap}
.wrapped-total-label{margin:8px 0 0;color:#9fb3c8;font-size:.9rem;text-transform:uppercase;letter-spacing:.08em}
.wrapped-analogy{margin:10px 0 0;color:#dce2ea;font-size:.96rem;line-height:1.55}
.wrapped-art{display:grid;place-items:center}
.wrapped-art img{width:min(180px,100%);height:auto;image-rendering:auto;filter:drop-shadow(0 14px 28px rgba(0,0,0,.42)) drop-shadow(0 0 22px rgba(247,120,186,.22))}
.wrapped-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.wrapped-metric{padding:13px 14px;border:1px solid #2a313a;border-radius:10px;background:rgba(9,12,16,.82);min-width:0}
.wrapped-metric span{display:block;color:#8b949e;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
.wrapped-metric b{display:block;color:#f0f6fc;font-size:1rem;line-height:1.35;overflow-wrap:anywhere}
.contribution-wrap{display:grid;gap:14px;align-items:start}
.contribution-heatmap{min-width:0}
.contribution-months{display:grid;grid-template-columns:repeat(var(--weeks),minmax(0,1fr));gap:3px;padding-left:30px;margin-bottom:6px;color:#8b949e;font-size:.7rem;letter-spacing:.01em}
.contribution-months span{min-height:1em;white-space:nowrap;overflow:visible}
.contribution-board{display:grid;grid-template-columns:24px minmax(0,1fr);gap:6px;align-items:stretch}
.contribution-days{display:grid;grid-template-rows:repeat(7,1fr);gap:3px;color:#8b949e;font-size:.6rem;line-height:1;padding-top:0}
.contribution-grid{display:grid;grid-template-columns:repeat(var(--weeks),minmax(0,1fr));grid-template-rows:repeat(7,auto);grid-auto-flow:column;gap:3px}
.contribution-cell{display:block;width:100%;aspect-ratio:1;border-radius:2px;background:#161b22;border:1px solid rgba(255,255,255,.04)}
.contribution-cell.level-1{background:#0e4429}
.contribution-cell.level-2{background:#006d32}
.contribution-cell.level-3{background:#26a641}
.contribution-cell.level-4{background:#39d353}
.contribution-legend{display:flex;justify-content:flex-end;align-items:center;gap:6px;margin-top:10px;color:#8b949e;font-size:.72rem}
.contribution-legend .contribution-cell{width:12px;min-width:12px;height:12px;aspect-ratio:auto}
.contribution-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.contribution-stat{padding:13px 14px;border:1px solid #2a313a;border-radius:8px;background:#090b0e}
.contribution-stat span{display:block;color:#8b949e;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:7px}
.contribution-stat b{display:block;color:#f0f6fc;font-size:1rem;line-height:1.35;overflow-wrap:anywhere}
@media (max-width:780px){.wrap{padding:28px 14px}header{display:block}.meta{text-align:left;margin-top:16px}.header-actions{align-items:flex-start;margin-top:16px}.cards{grid-template-columns:repeat(2,1fr)}.rank-head{display:none}.rank-list{display:grid;gap:10px}.rank-line{display:grid;grid-template-columns:1fr;gap:8px;padding:12px;border:1px solid #30363d;border-radius:6px;background:#090b0e}.rank-line .arrow{display:none}.rank-line .name{white-space:normal;font-weight:700;color:#f0f6fc}.rank-line .pct,.rank-line .tokens,.rank-line .cost{display:flex;justify-content:space-between;gap:14px;text-align:left}.rank-line .pct::before,.rank-line .tokens::before,.rank-line .cost::before{content:attr(data-label);color:var(--muted)}.tools-head{display:none}.tool-row{grid-template-columns:1fr;gap:8px}.tool-row .pct,.tool-row .tokens,.tool-row .cost{display:flex;justify-content:space-between;gap:14px;text-align:left}.tool-row .pct:empty,.tool-row .tokens:empty,.tool-row .cost:empty{display:none}.tool-row .pct::before,.tool-row .tokens::before,.tool-row .cost::before{content:attr(data-label);color:var(--muted)}}
@media (max-width:780px){.wrapped-card{grid-template-columns:1fr;gap:16px}.wrapped-art{order:-1}.wrapped-art img{width:140px}.wrapped-metrics{grid-template-columns:1fr 1fr}.contribution-months{padding-left:30px}}
@media (max-width:480px){.wrap{padding:22px 12px 28px}h1{white-space:normal}.cards{grid-template-columns:repeat(2,1fr);gap:8px}.card{min-height:96px;padding:13px 11px}.share-dialog{width:100vw;max-width:none;height:100dvh;max-height:none;margin:0;border:0;border-radius:0}.share-modal{min-height:100dvh;padding:16px 12px 18px}.share-section{padding:12px}.share-action{min-height:42px;font-size:.72rem;gap:4px;white-space:normal}.share-file-actions{grid-template-columns:1fr}.section{padding:16px 12px}.wrapped-metrics{grid-template-columns:1fr}.contribution-stats{grid-template-columns:1fr}.contribution-months{font-size:.66rem;padding-left:26px}.contribution-board{grid-template-columns:22px minmax(0,1fr)}.contribution-days{font-size:.58rem}}"""
