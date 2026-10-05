import { t } from './strings'
import type { Quotas, Window } from '../types'
export function byTightest(data: Quotas, order: readonly string[], now = Date.now(), elapsedSeconds = 0): string[] {
  return order.map((key, index) => {
    const agent = data.agents[key]
    const windows = [agent?.five_hour, agent?.seven_day, agent?.period, ...(agent?.groups ?? []).flatMap(group => [group.five_hour, group.seven_day])]
    const used = Math.max(-Infinity, ...windows.map(window => window ? effectivePercent(window, now, elapsedSeconds) : undefined).filter((value): value is number => typeof value === 'number' && Number.isFinite(value)))
    return { key, index, used, available: agent?.available === true }
  }).sort((a,b) => Number(b.available) - Number(a.available) || b.used - a.used || a.index - b.index).map(row => row.key)
}
// agy and Grok are optional, so like the menu bar they stay hidden unless they are set up and failing.
export function showsUnavailable(key: string, reason?: string): boolean {
  return key === 'claude-code' || key === 'codex' || reason === 'error'
}
export function parseQuota(text: string): Quotas {
  // A window without a numeric used_percent has no data; drop it so it is hidden instead of drawn as 0%.
  const value = JSON.parse(text, (_key, v) =>
    v && typeof v === 'object' && 'used_percent' in v && !Number.isFinite(v.used_percent) ? undefined : v)
  if (!value || typeof value.agents !== 'object' || value.agents === null) throw new Error(t('quota_invalid'))
  const agents = Object.fromEntries(Object.entries(value.agents).filter(([, agent]) =>
    agent !== null && typeof agent === 'object').map(([key, agent]) => {
    const row = agent as Quotas['agents'][string]
    return [key, row.available === true ? row : { available: false, reason: ['not_signed_in','no_data','error'].includes(row.reason ?? '') ? row.reason : 'no_data' }]
  })) as Quotas['agents']
  // agy's Claude / GPT pool barely moves and the menu bar panel already shows it; in the pane it is noise.
  const agy = agents.antigravity
  if (agy?.groups) agents.antigravity = { ...agy, groups: agy.groups.filter(group => !['CLAUDE AND GPT MODELS', 'Claude / GPT'].includes(group.name)) }
  return { agents }
}
export function hideAgents(data: Quotas, preferences: string): Quotas {
  let value: unknown
  try { value = JSON.parse(preferences) } catch { return { ...data, agents: { ...data.agents } } }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return { ...data, agents: { ...data.agents } }
  const keys: Record<string,string> = { hide_claude_section:'claude-code', hide_codex_section:'codex', hide_agy_section:'antigravity', hide_grok_section:'grok' }
  const hidden = new Set(Object.entries(keys).filter(([key]) => (value as Record<string,unknown>)[key] === true).map(([,agent]) => agent))
  return { ...data, agents: Object.fromEntries(Object.entries(data.agents).filter(([agent]) => !hidden.has(agent))) }
}
export function countdown(seconds: number): string {
  const s = Math.max(0, Number.isFinite(seconds) ? seconds : 0)
  if (s < 3600) return t('minutes', { count: Math.floor(s / 60) })
  if (s < 86400) return t('hours', { count: Math.floor(s / 3600) })
  return t('days', { count: Math.floor(s / 86400) })
}
export function effectivePercent(window: Window, now: number, elapsedSeconds = 0): number {
  const reset = window.resets_at ?? (now / 1000 - elapsedSeconds + (window.resets_in_seconds ?? Infinity))
  return reset <= now / 1000 ? 0 : window.used_percent
}
export function quotaLine(label: string, window: Window, now: number, ageSeconds = 0, bodyColumns?: number) {
  const used = effectivePercent(window, now, ageSeconds)
  const percent = Math.max(0, Math.min(100, Number.isFinite(used) ? used : 0))
  const barWidth = bodyColumns === undefined ? 16 : Math.max(10, Math.min(20, Math.floor(bodyColumns - 24)))
  const filled = Math.round(percent * barWidth / 100)
  const seconds = window.resets_at === undefined ? (window.resets_in_seconds ?? 0) - ageSeconds : window.resets_at - now / 1000
  // CJK characters take two columns; pad every label to the width of 5小時
  const width = [...label].reduce((sum, ch) => sum + (ch.charCodeAt(0) > 0xff ? 2 : 1), 0)
  const parts = {
    label: `${label}${' '.repeat(Math.max(0, 5 - width))} `,
    filled: '━'.repeat(filled),
    empty: '─'.repeat(barWidth - filled),
    percent: `${Math.round(percent)}%`.padStart(4),
    countdown: ` ↻${seconds <= 0 && (window.resets_at !== undefined || window.resets_in_seconds !== undefined) ? t('reset_done') : countdown(seconds)}`,
  }
  return { ...parts, text: `${parts.label}${parts.filled}${parts.empty} ${parts.percent}${parts.countdown}`,
    color: percent >= 80 ? 'red' : percent >= 50 ? 'yellow' : 'green' }
}

export function fmtDuration(seconds: number): string {
  if (seconds >= 86400) return `${Math.floor(seconds / 86400)}d${Math.floor(seconds % 86400 / 3600)}h`
  if (seconds >= 3600) return `${Math.floor(seconds / 3600)}h${Math.floor(seconds % 3600 / 60)}m`
  if (seconds >= 60) return `${Math.floor(seconds / 60)}min`
  return `${Math.trunc(seconds)}s`
}
export function progressParts(value: number, bodyColumns = 44) {
  const percent = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0))
  const width = bodyColumns < 44 ? 8 : 10
  // Python's round uses the even neighbour for exact halves.
  const round = (value: number) => value % 1 === 0.5 ? 2 * Math.round(value / 2) : Math.round(value)
  const filled = round(percent * width / 100)
  return { filled: '■'.repeat(filled), empty: '□'.repeat(width - filled), percent: `${round(percent)}%`,
    color: percent < 50 ? '#00d787' : percent < 80 ? '#ffaf00' : '#d70000' }
}
export function resetTime(window: Window, now: number, elapsedSeconds = 0): string {
  const reset = window.resets_at ?? (now / 1000 - elapsedSeconds + (window.resets_in_seconds ?? Infinity))
  if (reset <= now / 1000) return t('reset_done')
  const remain = Math.trunc(reset) - Math.trunc(now / 1000)
  if (!Number.isFinite(remain)) return ''
  const word = t('remaining'), duration = fmtDuration(remain)
  return word === '剩' ? `${word}${duration}` : `${duration} ${word}`
}
export function dockQuotaLine(label: string, window: Window, now: number, elapsedSeconds = 0, bodyColumns = 44) {
  const parts = progressParts(effectivePercent(window, now, elapsedSeconds), bodyColumns)
  const width = [...label].reduce((sum, ch) => sum + (ch.charCodeAt(0) > 0xff ? 2 : 1), 0)
  const time = resetTime(window, now, elapsedSeconds)
  return { ...parts, label: `${label}${' '.repeat(Math.max(0, 5 - width))} `,
    percent: parts.percent.padStart(4), countdown: time ? `  ${time}` : '' }
}
export function refreshedAgo(now: number, last: number | null): string {
  if (last === null) return '↻ —'
  const seconds = Math.max(0, Math.floor((now - last) / 1000))
  return `↻ ${seconds < 60 ? t('seconds_ago', { count: seconds }) : t(seconds < 3600 ? 'minutes_ago' : 'hours_ago', { count: Math.floor(seconds / (seconds < 3600 ? 60 : 3600)) })}`
}
export function staleAge(ageSeconds: number, now: number, last: number | null): string {
  const age = Math.max(0, ageSeconds + (last === null ? 0 : (now - last) / 1000))
  if (age <= 600) return ''
  return ` · ${t(age >= 3600 ? 'hours_ago' : 'minutes_ago', { count: Math.floor(age / (age >= 3600 ? 3600 : 60)) })}`
}
