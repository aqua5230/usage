import { t } from './strings'
import type { Quotas, Session, Window } from '../types'
import { quotaLine } from './quota'
import { isBusy } from './sessions'

export type CompactPart = { text: string; color?: string; bold?: boolean }
export function compactLines(data: Quotas, sessions: Session[], running: number, now: number, last: number | null): [CompactPart[], CompactPart[], CompactPart[]] {
  const first: CompactPart[] = [], second: CompactPart[] = []
  function percent(row: CompactPart[], window: Window | undefined) {
    if (!window) return
    const line = quotaLine('', window, now)
    row.push({ text: line.percent.trim(), color: line.color })
  }
  for (const [key, name, color, row] of [
    ['claude-code', 'Claude', '#d97757', first],
    ['codex', 'Codex', '#10a37f', first],
    ['antigravity', 'agy', '#4285f4', second],
    ['grok', 'Grok', 'white', second],
  ] as const) {
    const agent = data.agents[key]
    if (!agent?.available) continue
    if (row.length) row.push({ text: '   ' })
    row.push({ text: `◆ ${name}`, color, bold: key === 'grok' })
    if (key === 'antigravity') {
      let hasGroup = false
      for (const group of agent.groups ?? [{ name: '', five_hour: agent.five_hour, seven_day: agent.seven_day }]) {
        if (!group.five_hour && !group.seven_day) continue
        const label = group.name === 'GEMINI MODELS' ? 'Gemini' : ['CLAUDE AND GPT MODELS', 'Claude / GPT'].includes(group.name) ? 'Claude/GPT' : group.name
        row.push({ text: `${hasGroup ? '  ' : ' '}${label}${label ? ' ' : ''}` })
        percent(row, group.five_hour)
        if (group.five_hour && group.seven_day) row.push({ text: '/' })
        percent(row, group.seven_day)
        hasGroup = true
      }
    } else if (key === 'grok') {
      if (agent.period) row.push({ text: ' ' })
      percent(row, agent.period)
    } else {
      for (const [label, window] of [[t('five_hour'), agent.five_hour], [t('week'), agent.seven_day]] as const) {
        if (!window) continue
        row.push({ text: ` ${label} ` })
        percent(row, window)
      }
    }
  }
  return [first, second, [
    { text: t('compact_summary', { busy: sessions.filter(isBusy).length, total: sessions.length }) },
    { text: String(running), color: running > 0 ? 'yellow' : undefined },
    { text: ` · ${last === null ? '↻ —' : `↻ ${t('seconds_ago', { count: Math.max(0, Math.floor((now-last)/1000)) })}`}` },
  ]]
}
