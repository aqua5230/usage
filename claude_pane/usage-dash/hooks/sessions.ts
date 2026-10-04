import { t } from './strings'
import type { Session } from '../types'
export function parseSession(text: string): Pick<Session, 'title' | 'source'> & { preview: string } {
  let title = '', prompt = '', source = '', preview = ''
  for (const line of text.split('\n')) {
    let row
    try { row = JSON.parse(line) } catch { continue }
    if (!row || typeof row !== 'object') continue
    if (row.type === 'ai-title' && typeof row.aiTitle === 'string') title = row.aiTitle.trim()
    if (row.type === 'last-prompt' && typeof row.lastPrompt === 'string') prompt = row.lastPrompt.trim()
    if (typeof row.entrypoint === 'string') source = row.entrypoint
    if (row.type === 'assistant' && row.isSidechain !== true) {
      const content = row.message?.content
      const text = typeof content === 'string' ? content : Array.isArray(content) ? content.filter(block => block?.type === 'text' && typeof block.text === 'string').map(block => block.text).join(' ') : ''
      const clean = text.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\*\*|__|`/g, '').replace(/^\s*(?:#+\s*|[-*>]\s+|\d+[.)]\s+)/gm, '').replace(/\s+/g, ' ').trim().slice(0,200)
      if (clean) preview = clean
    }
  }
  return { title: title || prompt || t('untitled'), source: source === 'cli' ? t('terminal') : source === 'claude-desktop' ? t('desktop') : source, preview }
}
export type LiveSession = { pid: number; sessionId: string; name: string; entrypoint: string; status: string; statusUpdatedAt: number; cwd: string; waitingFor?: string }
export function parseLiveSession(text: string): LiveSession | null {
  let row
  try { row = JSON.parse(text) } catch { return null }
  if (!row || typeof row !== 'object' || !Number.isSafeInteger(row.pid) || row.pid <= 0 || typeof row.sessionId !== 'string' || !row.sessionId) return null
  const timestamp = row.statusUpdatedAt ?? row.updatedAt
  if (typeof timestamp !== 'number' || !Number.isFinite(timestamp)) return null
  return { pid: row.pid, sessionId: row.sessionId, name: typeof row.name === 'string' ? row.name : '', entrypoint: typeof row.entrypoint === 'string' ? row.entrypoint : '', status: typeof row.status === 'string' ? row.status : '', statusUpdatedAt: timestamp, cwd: typeof row.cwd === 'string' ? row.cwd : '', ...(typeof row.waitingFor === 'string' && row.waitingFor.trim() ? { waitingFor: row.waitingFor } : {}) }
}
export function liveSessions(rows: LiveSession[], psOutput: string): LiveSession[] {
  const pids = new Set(psOutput.trim().split(/\s+/).map(Number))
  return rows.filter(row => pids.has(row.pid))
}
export function tasklistPids(output: string): string {
  return output.split(/\r?\n/).map(line => line.match(/^"(?:[^"]|"")*","([^"]*)"/)?.[1]).filter((pid): pid is string => !!pid).join(' ')
}
export function toSession(row: LiveSession, transcript = ''): Session {
  const { title, preview } = parseSession(transcript)
  let cwd = row.cwd
  if (!cwd) for (const line of transcript.split('\n')) {
    try { const entry = JSON.parse(line); if (typeof entry?.cwd === 'string') cwd = entry.cwd } catch { /* skip malformed transcript rows */ }
  }
  return { id: row.sessionId, pid: row.pid, title: title === t('untitled') ? row.name : title, source: projectSource(cwd, row.entrypoint), mtimeMs: row.statusUpdatedAt, status: row.status, ...(preview ? { preview } : {}), ...(row.waitingFor ? { waitingFor: row.waitingFor } : {}) }
}
export function isBusy(session: Session): boolean { return session.status === 'busy' }
export function sessionNotifications(previous: Session[], next: Session[], currentId: string): { session: Session; kind: 'done' | 'waiting' }[] {
  const busy = new Set(previous.filter(isBusy).map(session => session.id))
  return next.filter(session => session.id !== currentId && (session.status === 'idle' || session.status === 'waiting') && busy.has(session.id)).map(session => ({ session, kind: session.status === 'waiting' ? 'waiting' : 'done' }))
}
export function waitingText(reason?: string): string {
  if (!reason?.trim()) return t('waiting')
  const keys: Record<string,string> = { 'input needed':'input', 'dialog open':'dialog', 'sandbox request':'sandbox', 'worker request':'worker', 'goal proposal':'goal' }
  const key = Object.hasOwn(keys,reason) ? keys[reason] : undefined
  return t('waiting_for', { reason: key ? t(`waiting_${key}`) : reason })
}
export function settleNotifications(pending: { id: string; kind: 'done' | 'waiting' }[], previous: Session[], next: Session[], currentId: string): { toast: { session: Session; kind: 'done' | 'waiting' }[]; pending: { id: string; kind: 'done' | 'waiting' }[] } {
  const toast = pending.flatMap(({ id, kind }) => {
    const session = next.find(session => session.id === id && id !== currentId && session.status === (kind === 'done' ? 'idle' : 'waiting'))
    return session ? [{ session, kind }] : []
  })
  return { toast, pending: sessionNotifications(previous,next,currentId).map(({session,kind}) => ({id:session.id,kind})) }
}
const SPINNER = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
// Spinner while working, ? while waiting on you, ✓ for ten minutes after finishing, then a gray dot.
export function sessionMark(session: Session, waiting: boolean, now: number): { text: string; color?: string } {
  if (waiting) return { text: '?', color: 'yellow' }
  if (isBusy(session)) return { text: SPINNER[Math.floor(now / 1000) % SPINNER.length]!, color: 'green' }
  return now - session.mtimeMs < 600000 ? { text: '✓', color: 'green' } : { text: '●' }
}
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
  const project = cwd.replace(/[\\/]+$/, '').split(/[\\/]+/).pop() || (cwd.startsWith('/') ? '/' : t('no_project'))
  return `${project}${entrypoint && entrypoint !== 'cli' ? ` · ${t('desktop')}` : ''}`
}
