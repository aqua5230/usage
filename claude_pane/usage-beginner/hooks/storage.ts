// The host has no file locks or atomic replacement. Two conversations writing in the
// same millisecond-scale window can still overwrite each other's changes. An interrupted
// write can leave a damaged file; glossary operations then stop quietly without overwriting it.
import type { EngineInterface } from 'claude-code'
import { clean } from './clean'
import { keyOf, termOf } from './glossary'
import type { Entry, Glossary } from './glossary'

const emptyGlossary = (): Glossary => ({ version: 1, terms: Object.create(null) })
const invalid = new Map<string, { length: number; hash: number; error: unknown }>()
const valid = new Map<string, { text: string; data: Glossary }>()

function cloneGlossary(data: Glossary): Glossary {
  const terms: Record<string, Entry> = Object.create(null)
  for (const [key, row] of Object.entries(data.terms)) {
    terms[key] = row.aliases ? { ...row, aliases: [...row.aliases] } : { ...row }
  }
  return data.quizzed_at === undefined ? { version: 1, terms } : { version: 1, terms, quizzed_at: data.quizzed_at }
}

function contentHash(text: string): number {
  let hash = 2166136261
  for (let i = 0; i < text.length; i++) hash = Math.imul(hash ^ text.charCodeAt(i), 16777619)
  return hash
}

function parseGlossary(path: string, text: string): Glossary {
  const cached = valid.get(path)
  if (cached?.text === text) return cloneGlossary(cached.data)
  const previous = invalid.get(path)
  if (previous?.length === text.length && previous.hash === contentHash(text)) throw previous.error
  try {
    const value = JSON.parse(text)
    // Optional fields are absent or non-negative numbers (integers for counts).
    const bad = (field: unknown, integer = false) =>
      field !== undefined && (!(integer ? Number.isInteger(field) : Number.isFinite(field)) || (field as number) < 0)
    if (value?.version !== 1 || !value.terms || typeof value.terms !== 'object' || Array.isArray(value.terms) || bad(value.quizzed_at)) {
      throw new Error('Invalid glossary.json')
    }
    const data = emptyGlossary()
    for (const [key, raw] of Object.entries(value.terms)) {
      const row = raw as Entry, term = termOf(raw)
      if (!term || keyOf(term.term) !== key || typeof row.known !== 'boolean' ||
          !Number.isFinite(row.first_seen) || row.first_seen < 0 || bad(row.last_seen) || bad(row.review_at) || bad(row.reviews, true) || bad(row.user_typed_at) ||
          !Number.isInteger(row.seen_count) || row.seen_count < 1) throw new Error('Invalid glossary entry')
      let aliases: string[] | undefined
      if (row.aliases !== undefined) {
        if (!Array.isArray(row.aliases)) throw new Error('Invalid glossary entry')
        aliases = []
        for (const alias of row.aliases) {
          if (typeof alias !== 'string') throw new Error('Invalid glossary entry')
          const cleaned = clean(alias, 40)
          if (!cleaned) throw new Error('Invalid glossary entry')
          aliases.push(cleaned)
        }
      }
      data.terms[key] = {
        ...term, first_seen: row.first_seen, ...(row.last_seen === undefined ? {} : { last_seen: row.last_seen }),
        seen_count: row.seen_count, known: row.known,
        ...(row.review_at === undefined ? {} : { review_at: row.review_at }), ...(row.reviews === undefined ? {} : { reviews: row.reviews }),
        ...(row.user_typed_at === undefined ? {} : { user_typed_at: row.user_typed_at }),
        ...(aliases?.length ? { aliases } : {}),
      }
    }
    if (value.quizzed_at !== undefined) data.quizzed_at = value.quizzed_at
    invalid.delete(path)
    valid.set(path, { text, data: cloneGlossary(data) })
    return data
  } catch (error) {
    valid.delete(path)
    invalid.set(path, { length: text.length, hash: contentHash(text), error })
    throw error
  }
}

export async function readGlossary($: EngineInterface, path: string): Promise<Glossary> {
  if (await $.fs.exists(path)) return parseGlossary(path, await $.fs.read(path))
  invalid.delete(path)
  valid.delete(path)
  return emptyGlossary()
}

// Mutations are synchronous. Return undefined when there is no change to save.
export async function updateGlossary<T>($: EngineInterface, path: string, mutate: (data: Glossary) => T | undefined): Promise<T | undefined> {
  const data = await $.fs.exists(path)
    ? parseGlossary(path, await $.fs.read(path))
    : (invalid.delete(path), valid.delete(path), emptyGlossary())
  const result = mutate(data)
  if (result !== undefined) {
    const written = JSON.stringify(data)
    await $.fs.write(path, written)
    invalid.delete(path)
    valid.set(path, { text: written, data: cloneGlossary(data) })
  }
  return result
}
