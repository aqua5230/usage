export type Agent = 'codex' | 'agy' | 'grok' | 'muse'
export type Run = { id: string; agent: Agent; label: string; start: number; end: number | null; status: string }
export type BgTask = { id: string; type: string; label: string; start: number }
export type Window = { used_percent: number; resets_in_seconds?: number; resets_at?: number }
export type QuotaAgent = { available: boolean; reason?: 'not_signed_in' | 'no_data' | 'error'; model?: string; tier?: string; age_seconds?: number; five_hour?: Window; seven_day?: Window; period?: Window; groups?: { name: string; five_hour?: Window; seven_day?: Window }[] }
export type Quotas = { agents: Record<string, QuotaAgent> }
export type Session = { id: string; title: string; source: string; mtimeMs: number; pid: number; status: string; preview?: string; waitingFor?: string; contextPercent?: number; contextTokens?: number; images?: number; toolTokens?: number; waiting?: boolean; waitingUpdatedAt?: number; jobs?: number }
declare module 'claude-code' {
  interface PluginState {
    'usage-dash': {
      quotas: Quotas; updated: number | null; quotaError: string; sessions: Session[]; sessionError: string; pendingToasts: { id: string; kind: 'done' | 'waiting' }[];
      runs: Run[]; bgTasks: BgTask[]; agents: AgentInfo[]; collapsed: { quota: boolean; sessions: boolean; runs: boolean }; more: boolean; moreRuns: boolean;
    }
  }
}
