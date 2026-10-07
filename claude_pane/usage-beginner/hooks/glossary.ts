import { clean } from './clean'

export type Term = { term: string; plain: string; example: string }
export type Entry = Term & {
  first_seen: number; last_seen?: number; seen_count: number; known: boolean; review_at?: number; reviews?: number
}
export type Glossary = { version: 1; terms: Record<string, Entry>; quizzed_at?: number }
export type Quiz = { key: string; term: string; options: string[]; answer: number }
export const keyOf = (term: string): string => term.trim().toLowerCase()

export const DAY = 86_400_000
// A term shown without "All understood" waits longer each time: 1, 3, then 7 days.
export const hidden = (row: Entry, now: number): boolean =>
  row.known || now < (row.last_seen ?? row.first_seen) + [1, 3, 7][Math.min(row.seen_count, 3) - 1]! * DAY

// An understood term is quizzed 7, 21, then 60 days later; a wrong answer sends it back to the hints.
export const REVIEW_DAYS = [7, 21, 60]
export function withKnown(row: Entry, known: boolean, now: number): Entry {
  const { review_at: _at, reviews: _count, ...rest } = row
  return known ? { ...rest, known, review_at: now + REVIEW_DAYS[0]! * DAY, reviews: 0 } : { ...rest, known }
}
export function graded(row: Entry, correct: boolean, now: number): Entry {
  if (!correct) return withKnown(row, false, now)
  const { review_at: _at, ...rest } = row, reviews = (row.reviews ?? 0) + 1
  return reviews < REVIEW_DAYS.length ? { ...rest, reviews, review_at: now + REVIEW_DAYS[reviews]! * DAY } : { ...rest, reviews }
}

function shuffle<T>(items: T[], random: () => number): T[] {
  const out = [...items]
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [out[i], out[j]] = [out[j]!, out[i]!]
  }
  return out
}
const escape = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// At most one quiz a day, on the understood term that has waited longest; the other options are other terms' explanations.
export function quizOf(data: Glossary, now: number, random: () => number): Quiz | undefined {
  if (data.quizzed_at !== undefined && now - data.quizzed_at < DAY) return undefined
  const due = Object.entries(data.terms)
    .filter(([, row]) => row.known && row.review_at !== undefined && row.review_at <= now)
    .sort(([, a], [, b]) => a.review_at! - b.review_at!)[0]
  if (!due) return undefined
  const [key, row] = due
  // Overlapping names ("branch", "分支 (branch)") are the same idea; an explanation naming the term gives it away.
  const others = [...new Set(Object.entries(data.terms)
    .filter(([other, o]) => !other.includes(key) && !key.includes(other) && !o.plain.toLowerCase().includes(key) && o.plain !== row.plain)
    .map(([, o]) => o.plain))]
  if (!others.length) return undefined
  const mask = new RegExp(escape(row.term.trim()), 'gi')
  const options = shuffle([row.plain, ...shuffle(others, random).slice(0, 3)], random)
  return { key, term: row.term, options: options.map(text => text.replace(mask, '___')), answer: options.indexOf(row.plain) }
}

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

