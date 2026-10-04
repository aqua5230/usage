import type { AgentInfo } from 'claude-code'
export type Agent = 'codex' | 'agy' | 'grok' | 'muse'
export type Run = { id: string; agent: Agent; label: string; start: number; end: number | null; status: string }
export type Window = { used_percent: number; resets_in_seconds?: number; resets_at?: number }
export type QuotaAgent = { available: boolean; model?: string; tier?: string; age_seconds?: number; five_hour?: Window; seven_day?: Window; period?: Window; groups?: { name: string; five_hour?: Window; seven_day?: Window }[] }
export type Quotas = { agents: Record<string, QuotaAgent> }
export type Session = { id: string; title: string; source: string; mtimeMs: number; pid: number; status: string; contextPercent?: number; waiting?: boolean; waitingUpdatedAt?: number }
declare module 'claude-code' {
  interface PluginState {
    'usage-dash': {
      quotas: Quotas; updated: number | null; quotaError: string; sessions: Session[]; sessionError: string;
      runs: Run[]; agents: AgentInfo[]; collapsed: { quota: boolean; sessions: boolean; runs: boolean }; more: boolean;
    }
  }
}
