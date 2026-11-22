import { clean } from './clean'

export type Term = { term: string; plain: string; example: string }
export type Candidate = Term & { sourceTerm: string }
export type Entry = Term & {
  first_seen: number; last_seen?: number; seen_count: number; known: boolean; review_at?: number; reviews?: number; user_typed_at?: number
}
export type Glossary = { version: 1; terms: Record<string, Entry>; quizzed_at?: number }
export type Quiz = { key: string; term: string; options: string[]; answer: number }
export const keyOf = (term: string): string => term.trim().toLowerCase()

// "分支（branch）" and "PR (pull request)" name one idea twice, so each half is another name for it.
const TWO_NAMES = /^(.+?)(?:\s*（\s*|\s+\(\s*)([^（）()]+?)\s*[）)]$/u
export function namesOf(term: string): string[] {
  const key = keyOf(term), parts = TWO_NAMES.exec(key)
  return parts ? [key, ...[parts[1]!, parts[2]!].filter(part => !isIdentifier(part))] : [key]
}
// Entries sharing a name with the term. One step only: "orchestrator (argon)" must not tie argon to neon.
export function sameIdea(data: Glossary, term: string): string[] {
  const names = new Set(namesOf(term))
  return Object.keys(data.terms).filter(key => namesOf(key).some(name => names.has(name)))
}

const asciiWord = /[A-Za-z0-9_]/, asciiLetterOrDigit = /[A-Za-z0-9]/
export function userTyped(term: string, text: string): boolean {
  if (text.length > 500) return false
  const key = keyOf(term), prompt = keyOf(text)
  if (key.length < 2) return false
  if (!asciiLetterOrDigit.test(key)) return prompt.includes(key)
  for (let at = prompt.indexOf(key); at !== -1; at = prompt.indexOf(key, at + 1)) {
    if (!asciiWord.test(prompt[at - 1] ?? '') && !asciiWord.test(prompt[at + key.length] ?? '')) return true
  }
  return false
}

export const DAY = 86_400_000
// A term shown without "All understood" waits longer each time: 1, 3, then 7 days.
export const hidden = (row: Entry, now: number): boolean =>
  row.known || row.user_typed_at !== undefined || now < (row.last_seen ?? row.first_seen) + [1, 3, 7][Math.min(row.seen_count, 3) - 1]! * DAY

// An understood term is quizzed 7, 21, then 60 days later; a wrong answer sends it back to the hints.
export const REVIEW_DAYS = [7, 21, 60]
export function withKnown(row: Entry, known: boolean, now: number): Entry {
  if (known && row.known) return row
  const { review_at: _at, reviews: _count, ...rest } = row
  if (known) return { ...rest, known, review_at: now + REVIEW_DAYS[0]! * DAY, reviews: 0 }
  const { user_typed_at: _typed, ...unknown } = rest
  return { ...unknown, known }
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
    // A word the user types themselves needs no quiz.
    .filter(([, row]) => row.known && row.user_typed_at === undefined && row.review_at !== undefined && row.review_at <= now)
    .sort(([, a], [, b]) => a.review_at! - b.review_at!)[0]
  if (!due) return undefined
  const [key, row] = due, same = new Set(sameIdea(data, key))
  // Overlapping names ("branch", "分支 (branch)") are the same idea; an explanation naming the term gives it away.
  const others = [...new Set(Object.entries(data.terms)
    .filter(([other, o]) => !same.has(other) && !other.includes(key) && !key.includes(other) && !o.plain.toLowerCase().includes(key) && o.plain !== row.plain)
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
  // The prompt asks for 30 characters; the caps only stop a runaway reply.
  const term = clean(row.term, 40), plain = clean(row.plain, 80), example = clean(row.example, 120)
  return term && plain && example ? { term, plain, example } : null
}

export const MAX_CANDIDATES = 8

function parseArray(text: string, requireValidFields = false): Candidate[] | undefined {
  let rows: unknown
  try { rows = JSON.parse(text) } catch { return undefined }
  if (!Array.isArray(rows)) return undefined
  const terms: Candidate[] = []
  for (const raw of rows.slice(0, MAX_CANDIDATES)) {
    const term = termOf(raw)
    if (term) terms.push({ ...term, sourceTerm: raw.term.trim() })
    else if (requireValidFields) return undefined
  }
  return terms
}

function arrayEnd(text: string, start: number): number {
  let depth = 0, quoted = false
  for (let i = start; i < text.length; i++) {
    const char = text[i]
    if (quoted) {
      if (char === '\\') i++
      else if (char === '"') quoted = false
    } else if (char === '"') quoted = true
    else if (char === '[') depth++
    else if (char === ']' && --depth === 0) return i
  }
  return -1
}

export function parseTerms(text: string): Candidate[] {
  const whole = parseArray(text)
  if (whole) return whole
  for (const [, block] of text.matchAll(/```json[ \t]*\r?\n([\s\S]*?)\r?\n[ \t]*```/gi)) {
    const fenced = parseArray(block!)
    if (fenced) return fenced
  }
  let empty = false
  for (let start = text.indexOf('['); start !== -1; start = text.indexOf('[', start + 1)) {
    const end = arrayEnd(text, start)
    if (end === -1) continue
    const terms = parseArray(text.slice(start, end + 1), true)
    if (terms?.length) return terms
    if (terms) empty = true
  }
  if (empty) return []
  throw new Error('Expected a JSON array')
}

export function isIdentifier(term: string): boolean {
  if ((/\s/.test(term) && /\p{L}/u.test(term)) || /^(?:--?)?[\p{L}_][\p{L}\p{N}_.-]*=\S+$/u.test(term)) return false
  // Concepts that look like paths or file names: slash commands (/compact), short letter pairs (CI/CD, I/O,
  // async/await; feat/example stays out) and framework names (Node.js, Next.js).
  if (/^\/[a-z][a-z-]*$/i.test(term) || /^[a-z]{1,5}(?:\/[a-z]{1,5})+$/i.test(term) || /^[A-Z][a-z]+\.js$/.test(term)) return false
  return /^(?:[a-z]:)?[\p{L}\p{N}._~@%+-]*\/[\p{L}\p{N}._~@%+/-]*(?::\d+)?$/iu.test(term) ||
    /^#\s*\d+$/u.test(term) || /^[\p{N}\p{P}\p{S}\s]+$/u.test(term) ||
    /^[^\s/\\]+\.\p{L}[\p{L}\p{N}]*(?::\d+)?$/u.test(term) ||
    /^(?:v\d+|\d+\.\d+)(?:\.\d+)*(?:[-+][\w.-]+)?$/i.test(term) ||
    /^[\da-f]{7,}$/i.test(term) || /^(?:[a-z][\da-z+.-]*:\/\/|www\.|mailto:|data:)/i.test(term)
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
    const value = JSON.parse(text), window = value?.rate_limits?.five_hour
    const used = window?.used_percentage, reset = window?.resets_at
    const observations = value?._rate_limits_observed_at, clock = now / 1000
    const perWindow = observations != null && typeof observations === 'object'
    const stamp = perWindow ? observations.five_hour : value?._received_at_ts
    if (!Number.isFinite(used) || used < 90 || !Number.isFinite(stamp) || clock < stamp) return false
    if (Number.isFinite(reset)) {
      if (clock >= reset) return false
      if (perWindow) return true
    }
    return clock - stamp <= 900
  } catch { return false }
}

