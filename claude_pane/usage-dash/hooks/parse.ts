import { t } from './strings'
import type { Agent } from '../types'

// A dispatch starts a command segment: line start, or after && || ; | — optionally behind VAR=value prefixes.
const DISPATCH = /(?:^|&&|\|\||[;|\n])\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*(codex exec|agy -p|grok --prompt-file|muse exec)(?=\s|$)/

const AGENT_OF: Record<string, Agent> = {
  'codex exec': 'codex',
  'agy -p': 'agy',
  'grok --prompt-file': 'grok',
  'muse exec': 'muse',
}

export function matchAgent(command: string): Agent | null {
  // drop heredoc bodies only: a brief written with cat <<'EOF' may come before the dispatch line
  const head = command.replace(/<<-?\s*(['"]?)(\w+)\1[^\n]*\n[\s\S]*?\n\s*\2[ \t]*(?=\n|$)/g, '')
  if (/\s--help(?=\s|$)/.test(head)) return null
  const key = DISPATCH.exec(head)?.[1]
  return key ? (AGENT_OF[key] ?? null) : null
}

// A trailing lone & backgrounds in the shell: the tool call returns at once and no notification follows.
export function isShellBackgrounded(command: string): boolean {
  return /(?:^|[^&])&\s*$/.test(command.trimEnd())
}

// The task-notification text format is not a typed field; parse.test.ts pins it.
export function parseNotifications(text: string): { toolUseId: string; status: string }[] {
  return text
    .split('<task-notification>')
    .slice(1)
    .flatMap(block => {
      const id = /<tool-use-id>([^<]+)<\/tool-use-id>/.exec(block)?.[1]
      const status = /<status>([^<]+)<\/status>/.exec(block)?.[1]
      return id && status ? [{ toolUseId: id, status }] : []
    })
}

export function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  if (s < 60) return t('seconds', { count: s })
  const m = Math.floor(s / 60)
  if (m < 60) return `${t('minutes', { count: m })}${t('seconds', { count: String(s % 60).padStart(2, '0') })}`
  return `${t('hours', { count: Math.floor(m / 60) })}${t('minutes', { count: String(m % 60).padStart(2, '0') })}`
}

