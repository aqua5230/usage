import { clean } from './clean'

export type Term = { term: string; plain: string; example: string }
export type Entry = Term & { first_seen: number; last_seen?: number; seen_count: number; known: boolean }
export type Glossary = { version: 1; terms: Record<string, Entry> }
export const keyOf = (term: string): string => term.trim().toLowerCase()

const DAY = 86_400_000
// A term shown without "All understood" waits longer each time: 1, 3, then 7 days.
export const hidden = (row: Entry, now: number): boolean =>
  row.known || now < (row.last_seen ?? row.first_seen) + [1, 3, 7][Math.min(row.seen_count, 3) - 1]! * DAY

export function termOf(value: unknown): Term | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Record<string, unknown>
  if (typeof row.term !== 'string' || typeof row.plain !== 'string' || typeof row.example !== 'string') return null
  const term = clean(row.term, 40), plain = clean(row.plain, 40), example = clean(row.example, 80)
  return term && plain && example ? { term, plain, example } : null
}

export function parseTerms(text: string): Term[] {
  // Models often wrap the array in a code fence or a sentence; parse from the first [ to the last ].
  const start = text.indexOf('['), end = text.lastIndexOf(']')
  if (start === -1 || end <= start) throw new Error('Expected a JSON array')
  const rows: unknown = JSON.parse(text.slice(start, end + 1))
  if (!Array.isArray(rows)) throw new Error('Expected a JSON array')
  return rows.slice(0, 8).map(termOf).filter((row): row is Term => row !== null)
}

const LANGUAGES: Record<string, string> = {
  'zh-TW': 'Traditional Chinese as written in Taiwan, with Taiwan wording',
  'zh-CN': 'Simplified Chinese as written in mainland China',
  ja: 'Japanese',
  ko: 'Korean',
  en: 'English',
}
export const languageName = (lang: string): string => LANGUAGES[lang] ?? 'English'

export function quotaPaused(text: string, now: number): boolean {
  try {
    const value = JSON.parse(text), used = value?.rate_limits?.five_hour?.used_percentage, stamp = value?._received_at_ts
    return typeof used === 'number' && Number.isFinite(used) && used >= 90 &&
      typeof stamp === 'number' && Number.isFinite(stamp) && now / 1000 - stamp >= 0 && now / 1000 - stamp <= 900
  } catch { return false }
}

