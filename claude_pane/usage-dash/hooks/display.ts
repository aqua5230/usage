import { t } from './strings'
import type { Run } from '../types'
import { ago } from './sessions'
export type LiveContext = { sessionId: string; percent: number; updatedAt: number }
export function contextPercent(percent: number | undefined): number | undefined {
  return typeof percent === 'number' && Number.isFinite(percent) ? Math.round(Math.max(0, Math.min(100, percent))) : undefined
}
export function contextColor(percent: number): 'yellow' | 'red' | undefined {
  return percent >= 85 ? 'red' : percent >= 70 ? 'yellow' : undefined
}
export function parseContext(text: string): LiveContext | null {
  try {
    const row = JSON.parse(text)
    if (!row || typeof row.sessionId !== 'string' || !row.sessionId || !Number.isInteger(row.percent) || row.percent < 0 || row.percent > 100 || typeof row.updatedAt !== 'number' || !Number.isFinite(row.updatedAt)) return null
    return { sessionId: row.sessionId, percent: row.percent, updatedAt: row.updatedAt }
  } catch { return null }
}
export function staleContext(sessionId: string, updatedAt: number, openIds: Set<string>, now: number): boolean {
  return !openIds.has(sessionId) && now - updatedAt > 86400000
}
export function completedAgo(run: Pick<Run, 'end' | 'status'>, now: number): string {
  return run.end === null ? '' : ` · ${t('completed_ago', { ago: ago(run.end, now), status: run.status === 'failed' ? t('failed') : t('completed') })}`
}
