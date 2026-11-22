// The host has no file locks or atomic replacement. Two conversations writing in the
// same millisecond-scale window can still overwrite each other's changes. An interrupted
// write can leave a damaged file; glossary operations then stop quietly without overwriting it.
import type { EngineInterface } from 'claude-code'
import { keyOf, termOf } from './glossary'
import type { Entry, Glossary } from './glossary'

const emptyGlossary = (): Glossary => ({ version: 1, terms: Object.create(null) })
const invalid = new Map<string, { length: number; hash: number; error: unknown }>()

function contentHash(text: string): number {
  let hash = 2166136261
  for (let i = 0; i < text.length; i++) hash = Math.imul(hash ^ text.charCodeAt(i), 16777619)
  return hash
}

function parseGlossary(path: string, text: string): Glossary {
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
      data.terms[key] = {
        ...term, first_seen: row.first_seen, ...(row.last_seen === undefined ? {} : { last_seen: row.last_seen }),
        seen_count: row.seen_count, known: row.known,
        ...(row.review_at === undefined ? {} : { review_at: row.review_at }), ...(row.reviews === undefined ? {} : { reviews: row.reviews }),
        ...(row.user_typed_at === undefined ? {} : { user_typed_at: row.user_typed_at }),
      }
    }
    if (value.quizzed_at !== undefined) data.quizzed_at = value.quizzed_at
    invalid.delete(path)
    return data
  } catch (error) {
    invalid.set(path, { length: text.length, hash: contentHash(text), error })
    throw error
  }
}

export async function readGlossary($: EngineInterface, path: string): Promise<Glossary> {
  if (await $.fs.exists(path)) return parseGlossary(path, await $.fs.read(path))
  invalid.delete(path)
  return emptyGlossary()
}

// Mutations are synchronous. Return undefined when there is no change to save.
export async function updateGlossary<T>($: EngineInterface, path: string, mutate: (data: Glossary) => T | undefined): Promise<T | undefined> {
  const data = await $.fs.exists(path) ? parseGlossary(path, await $.fs.read(path)) : emptyGlossary()
  const result = mutate(data)
  if (result !== undefined) await $.fs.write(path, JSON.stringify(data))
  return result
}
