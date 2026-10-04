import { expect, test } from 'claude-code/testing'
import { parseQuota, hideAgents, countdown, quotaLine, refreshedAgo } from './quota'
test('舊版 JSON 與 unavailable', () => {
  expect(parseQuota('{"agents":{"claude-code":{"available":true},"codex":{"available":false}}}')).toEqual({ agents: { 'claude-code': { available: true } } })
  expect(parseQuota('{"agents":{}}')).toEqual({ agents: {} })
})
test('隱藏區塊設定會移除對應工具且不改原資料', () => {
  const data = parseQuota('{"agents":{"claude-code":{"available":true},"codex":{"available":true},"antigravity":{"available":true},"grok":{"available":true}}}')
  expect(hideAgents(data,'{"hide_grok_section":true}').agents).not.toHaveProperty('grok')
  expect(hideAgents(data,'{"hide_claude_section":true,"hide_agy_section":true}').agents).toEqual({codex:{available:true},grok:{available:true}})
  expect(hideAgents(data,'{"hide_grok_section":false,"hide_codex_section":"true"}')).toEqual(data)
  expect(hideAgents(data,'broken')).toEqual(data)
  expect(hideAgents(data,'')).toEqual(data)
  expect(data.agents).toEqual({'claude-code':{available:true},codex:{available:true},antigravity:{available:true},grok:{available:true}})
})
for (const [seconds, text] of [[0,'0m'],[3540,'59m'],[3600,'1h'],[82800,'23h'],[86400,'1d'],[259200,'3d'],[-1,'0m']] as const) {
  test(`倒數 ${seconds}`, () => expect(countdown(seconds)).toBe(text))
}
test('百分比顏色與 16 格', () => {
  for (const [percent,color] of [[0,'green'],[49,'green'],[50,'yellow'],[79,'yellow'],[80,'red'],[100,'red']] as const) {
    const line = quotaLine('Week',{ used_percent: percent, resets_in_seconds: 0 },0)
    expect(line.color).toBe(color)
    expect(line.text.match(/[━─]+/)?.[0].length).toBe(16)
    expect(line.filled).toBe('━'.repeat(Math.round(percent * 16 / 100)))
    expect(line.empty).toBe('─'.repeat(16 - line.filled.length))
  }
})
test('倒數跟著更新後時間遞減', () => {
  expect(quotaLine('5h',{used_percent:10,resets_in_seconds:3600},0,60).text).toContain('↻59m')
  expect(quotaLine('5h',{used_percent:10,resets_at:3600},60000,60).text).toContain('↻59m')
  expect(() => parseQuota('')).toThrow()
})

test('窄寬面板與預設進度條', () => {
  for (const [columns, width] of [[10,10],[200,20],[undefined,16]] as const) {
    for (const percent of [0,100]) {
      const line = quotaLine('Week',{used_percent:percent,resets_in_seconds:-10},0,0,columns)
      expect(line.filled.length + line.empty.length).toBe(width)
      expect(line.filled.length).toBe(percent === 0 ? 0 : width)
      expect(line.percent).toBe(percent === 0 ? '  0%' : '100%')
      expect(line.countdown).toBe(' ↻0m')
    }
  }
})

import { dockQuotaLine, fmtDuration, progressParts, resetTime, staleAge } from './quota'
import { configure } from './strings'
for (const [pct, filled] of [[0,0],[33,3],[100,10]] as const) {
  test(`方塊條 ${pct}%`, () => {
    expect(progressParts(pct).filled).toBe('■'.repeat(filled))
    expect(progressParts(pct).empty).toBe('□'.repeat(10-filled))
  })
}
for (const [seconds, expected] of [[59,'59s'],[60,'1min'],[3599,'59min'],[86400,'1d0h'],[-1,'-1s']] as const) {
  test(`精確時長 ${seconds}`, () => expect(fmtDuration(seconds)).toBe(expected))
}
test('只顯示剩餘時間、跨日、過期、相對重置與寬度', () => {
  configure()
  const now = new Date(2026,9,5,0,0).getTime()
  const today = {used_percent:33,resets_at:now/1000+12000}
  expect(resetTime(today,now)).toBe('3h20m left')
  expect(resetTime({used_percent:33,resets_at:now/1000+5*86400+18*3600},now)).toBe('5d18h left')
  expect(resetTime({used_percent:0,resets_at:now/1000},now)).toBe('')
  expect(resetTime({used_percent:0,resets_at:now/1000-1},now)).toBe('')
  expect(resetTime({used_percent:0,resets_in_seconds:12060},now,60)).toBe('3h20m left')
  for (const window of [today, {used_percent:33,resets_at:now/1000+5*86400+18*3600}, {used_percent:0,resets_in_seconds:12060}]) {
    expect(resetTime(window,now,60)).not.toMatch(/[:/]/)
  }
  for (const [columns, width, empty] of [[43,8,5],[44,10,7]] as const) {
    const line = dockQuotaLine('5h',today,now,0,columns)
    expect(line.filled).toBe('■■■')
    expect(line.empty).toBe('□'.repeat(empty))
    expect(line.filled.length + line.empty.length).toBe(width)
  }
  for (const word of ['剩','left','残り','남음']) {
    configure({strings:{claude_pane_remaining:word}})
    expect(resetTime(today,now)).not.toMatch(/[:/]/)
    expect(resetTime(today,now)).toBe(word === '剩' ? '剩3h20m' : `3h20m ${word}`)
  }
  configure({strings:{claude_pane_remaining:'剩'}})
  const window = {used_percent:33,resets_at:now/1000+14160}
  expect(resetTime(window,now)).toBe('剩3h56m')
  expect(dockQuotaLine('5h',window,now).countdown).toBe('  剩3h56m')
  expect(dockQuotaLine('5h',{used_percent:0,resets_at:now/1000},now).countdown).toBe('')
  configure()
  expect(resetTime(window,now)).toBe('3h56m left')
  expect(dockQuotaLine('5h',window,now).countdown).toBe('  3h56m left')
})
test('舊資料只在超過十分鐘顯示，包含讀取後經過時間', () => {
  configure({strings:{claude_pane_minutes_ago:'{count}分前',claude_pane_hours_ago:'{count}時前'}})
  expect(staleAge(599,0,0)).toBe('')
  expect(staleAge(600,0,0)).toBe('')
  expect(staleAge(599,2000,0)).toBe(' · 10分前')
  expect(staleAge(601,0,0)).toBe(' · 10分前')
  expect(staleAge(61*60,0,0)).toBe(' · 1時前')
  configure()
})

test('寬版配色與四捨五入對齊 Python 狀態列', () => {
  expect([49,50,79,80].map(pct => progressParts(pct).color)).toEqual(['#00d787','#ffaf00','#ffaf00','#d70000'])
  expect(progressParts(85).filled).toBe('■'.repeat(8))
  expect(progressParts(54.5).percent).toBe('54%')
})

test('方塊條窄版、43／44 欄邊界、預設與寬版', () => {
  for (const [columns, width] of [[30,8],[43,8],[44,10],[60,10],[undefined,10]] as const) {
    for (const percent of [0,33,100]) {
      const parts = progressParts(percent,columns)
      expect(parts.filled.length + parts.empty.length).toBe(width)
      expect(parts.filled).toMatch(/^■*$/)
      expect(parts.empty).toMatch(/^□*$/)
      expect(parts.filled.length).toBe(percent === 0 ? 0 : percent === 100 ? width : 3)
    }
  }
})
test('刷新時間超過一分鐘換單位', () => {
  expect([null, 59000, 60000, 3599000, 3600000].map(age => refreshedAgo(10000000, age === null ? null : 10000000 - age)))
    .toEqual(['↻ —', '↻ 59s ago', '↻ 1m ago', '↻ 59m ago', '↻ 1h ago'])
})
test('沒有數字的額度窗口不顯示成 0%', () => {
  expect(parseQuota('{"agents":{"claude-code":{"available":true,"five_hour":{"used_percent":21},"seven_day":{"used_percent":null,"resets_at":null}}}}'))
    .toEqual({ agents: { 'claude-code': { available: true, five_hour: { used_percent: 21 } } } })
})
