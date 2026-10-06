import { t } from './strings'
import type { AgentInfo } from 'claude-code'
import type { Run, BgTask } from '../types'
import { ago } from './sessions'
export type LiveContext = { sessionId: string; percent?: number; tokens?: number; waiting?: boolean; jobs?: number; updatedAt: number }
export function contextPercent(percent: number | undefined): number | undefined {
  return typeof percent === 'number' && Number.isFinite(percent) ? Math.round(Math.max(0, Math.min(100, percent))) : undefined
}
export function contextColor(percent: number, tokens?: number): 'yellow' | 'red' | undefined {
  return percent >= 80 || (tokens !== undefined && tokens >= 400000) ? 'red' : percent >= 50 || (tokens !== undefined && tokens >= 200000) ? 'yellow' : undefined
}
export function parseContext(text: string): LiveContext | null {
  try {
    const row = JSON.parse(text)
    if (!row || typeof row.sessionId !== 'string' || !row.sessionId || (row.percent !== undefined && (!Number.isInteger(row.percent) || row.percent < 0 || row.percent > 100)) || (row.waiting !== undefined && typeof row.waiting !== 'boolean') || typeof row.updatedAt !== 'number' || !Number.isFinite(row.updatedAt)) return null
    return { sessionId: row.sessionId, ...(row.percent === undefined ? {} : { percent: row.percent }), ...(Number.isInteger(row.tokens) && row.tokens >= 0 ? { tokens: row.tokens } : {}), ...(row.waiting === undefined ? {} : { waiting: row.waiting }), ...(Number.isInteger(row.jobs) && row.jobs >= 0 ? { jobs: row.jobs } : {}), updatedAt: row.updatedAt }
  } catch { return null }
}
export function staleContext(sessionId: string, updatedAt: number, openIds: Set<string>, now: number): boolean {
  return !openIds.has(sessionId) && now - updatedAt > 86400000
}
export function completedAgo(run: Pick<Run, 'end' | 'status'>, now: number): string {
  return run.end === null ? '' : ` · ${t('completed_ago', { ago: ago(run.end, now), status: ['killed', 'stopped', 'cancelled'].includes(run.status) ? t('stopped') : run.status === 'failed' ? t('failed') : t('completed') })}`
}
export function isWaiting(context: Pick<LiveContext, 'waiting' | 'updatedAt'>, now: number): boolean {
  return context.waiting === true && now - context.updatedAt <= 600000
}
export function visibleAgents(agents: AgentInfo[]): AgentInfo[] {
  return agents.filter(agent => ['pending','running','waiting','idle'].includes(agent.status))
}
export function backgroundCount(runs: Pick<Run, 'end'>[], agents: AgentInfo[], tasks: BgTask[] = []): number {
  return tasks.length + runs.filter(run => run.end === null).length + visibleAgents(agents).length
}
// Running jobs always show; finished ones only fill the rows left out of four, unless expanded.
export function visibleRuns(runs: Run[], expanded: boolean, tasks: BgTask[] = []): { rows: (Omit<Run, 'agent'> & { agent: string })[]; hiddenDone: number } {
  const jobs = [...runs, ...tasks.map(task => ({ id: task.id, agent: task.type, label: task.label, start: task.start, end: null, status: 'running' }))]
  const done = jobs.filter(r => r.end !== null)
  const kept = new Set(expanded ? done : done.slice(Math.max(0, done.length - Math.max(0, 4 - (jobs.length - done.length)))))
  return { rows: jobs.filter(r => r.end === null || kept.has(r)), hiddenDone: done.length - kept.size }
}

export type ContextMix = { sessionId: string; transcript: string; offset: number; size: number; images: number; toolTokens: number; complete: boolean; updatedAt: number }
export function parseMix(text: string): ContextMix | null {
  try {
    const row = JSON.parse(text)
    if (!row || typeof row.sessionId !== 'string' || !/^[A-Za-z0-9_-]+$/.test(row.sessionId) || typeof row.transcript !== 'string' || !row.transcript || ['offset','size','images','toolTokens'].some(key => !Number.isSafeInteger(row[key]) || row[key] < 0) || row.offset > row.size || typeof row.complete !== 'boolean' || typeof row.updatedAt !== 'number' || !Number.isFinite(row.updatedAt) || row.updatedAt < 0) return null
    return { sessionId: row.sessionId, transcript: row.transcript, offset: row.offset, size: row.size, images: row.images, toolTokens: row.toolTokens, complete: row.complete, updatedAt: row.updatedAt }
  } catch { return null }
}
export function mixLabel(row: { contextPercent?: number; contextTokens?: number; images?: number; toolTokens?: number }): string {
  if (row.contextPercent === undefined || contextColor(row.contextPercent, row.contextTokens) === undefined || row.images === undefined || row.toolTokens === undefined) return ''
  const share = row.contextTokens && row.contextTokens > 0 ? Math.round(Math.max(0, Math.min(100, row.toolTokens / row.contextTokens * 100))) : 0
  return [...(row.images >= 1 ? [t('mix_images', { n: row.images })] : []), t('mix_tools', { n: share })].join(' ')
}
