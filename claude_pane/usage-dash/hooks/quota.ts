import { t } from './strings'
import type { Quotas, Window } from '../types'
export function parseQuota(text: string): Quotas {
  const value = JSON.parse(text)
  if (!value || typeof value.agents !== 'object' || value.agents === null) throw new Error(t('quota_invalid'))
  return { agents: Object.fromEntries(Object.entries(value.agents).filter(([, agent]) =>
    agent !== null && typeof agent === 'object' && (agent as { available?: boolean }).available === true)) } as Quotas
}
export function countdown(seconds: number): string {
  const s = Math.max(0, Number.isFinite(seconds) ? seconds : 0)
  if (s < 3600) return t('minutes', { count: Math.floor(s / 60) })
  if (s < 86400) return t('hours', { count: Math.floor(s / 3600) })
  return t('days', { count: Math.floor(s / 86400) })
}
export function quotaLine(label: string, window: Window, now: number, ageSeconds = 0, bodyColumns?: number) {
  const percent = Math.max(0, Math.min(100, Number.isFinite(window.used_percent) ? window.used_percent : 0))
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
    countdown: ` ↻${countdown(seconds)}`,
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
  const reset = window.resets_at ?? (now / 1000 - elapsedSeconds + (window.resets_in_seconds ?? 0))
  const remain = Math.trunc(reset) - Math.trunc(now / 1000)
  if (remain <= 0 || !Number.isFinite(remain)) return ''
  const word = t('remaining'), duration = fmtDuration(remain)
  return word === '剩' ? `${word}${duration}` : `${duration} ${word}`
}
export function dockQuotaLine(label: string, window: Window, now: number, elapsedSeconds = 0, bodyColumns = 44) {
  const parts = progressParts(window.used_percent, bodyColumns)
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
