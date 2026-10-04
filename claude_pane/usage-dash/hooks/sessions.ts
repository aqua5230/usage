import { t } from './strings'
import type { Session } from '../types'
export function parseSession(text: string): Pick<Session, 'title' | 'source'> {
  let title = '', prompt = '', source = ''
  for (const line of text.split('\n')) {
    let row
    try { row = JSON.parse(line) } catch { continue }
    if (!row || typeof row !== 'object') continue
    if (row.type === 'ai-title' && typeof row.aiTitle === 'string') title = row.aiTitle.trim()
    if (row.type === 'last-prompt' && typeof row.lastPrompt === 'string') prompt = row.lastPrompt.trim()
    if (typeof row.entrypoint === 'string') source = row.entrypoint
  }
  return { title: title || prompt || t('untitled'), source: source === 'cli' ? t('terminal') : source === 'claude-desktop' ? t('desktop') : source }
}
export type LiveSession = { pid: number; sessionId: string; name: string; entrypoint: string; status: string; statusUpdatedAt: number; cwd: string }
export function parseLiveSession(text: string): LiveSession | null {
  let row
  try { row = JSON.parse(text) } catch { return null }
  if (!row || typeof row !== 'object' || !Number.isSafeInteger(row.pid) || row.pid <= 0 || typeof row.sessionId !== 'string' || !row.sessionId) return null
  const timestamp = row.statusUpdatedAt ?? row.updatedAt
  if (typeof timestamp !== 'number' || !Number.isFinite(timestamp)) return null
  return { pid: row.pid, sessionId: row.sessionId, name: typeof row.name === 'string' ? row.name : '', entrypoint: typeof row.entrypoint === 'string' ? row.entrypoint : '', status: typeof row.status === 'string' ? row.status : '', statusUpdatedAt: timestamp, cwd: typeof row.cwd === 'string' ? row.cwd : '' }
}
export function liveSessions(rows: LiveSession[], psOutput: string): LiveSession[] {
  const pids = new Set(psOutput.trim().split(/\s+/).map(Number))
  return rows.filter(row => pids.has(row.pid))
}
export function toSession(row: LiveSession, transcript = ''): Session {
  const { title } = parseSession(transcript)
  let cwd = row.cwd
  if (!cwd) for (const line of transcript.split('\n')) {
    try { const entry = JSON.parse(line); if (typeof entry?.cwd === 'string') cwd = entry.cwd } catch { /* skip malformed transcript rows */ }
  }
  return { id: row.sessionId, pid: row.pid, title: title === t('untitled') ? row.name : title, source: projectSource(cwd, row.entrypoint), mtimeMs: row.statusUpdatedAt, status: row.status }
}
export function isBusy(session: Session): boolean { return session.status === 'busy' }
export function sessionStatus(session: Session, now: number): string {
  return isBusy(session) ? t('busy') : t('idle', { ago: ago(session.mtimeMs, now) })
}
export function newest(sessions: Session[]): Session[] {
  return [...sessions].sort((a,b) => Number(isBusy(b)) - Number(isBusy(a)) || b.mtimeMs - a.mtimeMs)
}

export function ago(time: number, now: number): string {
  const minutes = Math.max(0, Math.floor((now - time) / 60000))
  return minutes === 0 ? t('just_now') : t('minutes_ago', { count: minutes })
}
export function projectSource(cwd: string, entrypoint: string): string {
  const project = cwd.replace(/\/+$/, '').split('/').pop() || (cwd.startsWith('/') ? '/' : t('no_project'))
  return `${project}${entrypoint && entrypoint !== 'cli' ? ` · ${t('desktop')}` : ''}`
}
