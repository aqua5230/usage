import { t } from './strings'
import type { AgentInfo } from 'claude-code'
import type { Run, BgTask } from '../types'
import { ago } from './sessions'
export type LiveContext = { sessionId: string; percent?: number; waiting?: boolean; jobs?: number; updatedAt: number }
export function contextPercent(percent: number | undefined): number | undefined {
  return typeof percent === 'number' && Number.isFinite(percent) ? Math.round(Math.max(0, Math.min(100, percent))) : undefined
}
export function contextColor(percent: number): 'yellow' | 'red' | undefined {
  return percent >= 85 ? 'red' : percent >= 70 ? 'yellow' : undefined
}
export function parseContext(text: string): LiveContext | null {
  try {
    const row = JSON.parse(text)
    if (!row || typeof row.sessionId !== 'string' || !row.sessionId || (row.percent !== undefined && (!Number.isInteger(row.percent) || row.percent < 0 || row.percent > 100)) || (row.waiting !== undefined && typeof row.waiting !== 'boolean') || typeof row.updatedAt !== 'number' || !Number.isFinite(row.updatedAt)) return null
    return { sessionId: row.sessionId, ...(row.percent === undefined ? {} : { percent: row.percent }), ...(row.waiting === undefined ? {} : { waiting: row.waiting }), ...(Number.isInteger(row.jobs) && row.jobs >= 0 ? { jobs: row.jobs } : {}), updatedAt: row.updatedAt }
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
  const kept = new Set(expanded ? done : done.slice(done.length - Math.max(0, 4 - (jobs.length - done.length))))
  return { rows: jobs.filter(r => r.end === null || kept.has(r)), hiddenDone: done.length - kept.size }
}
