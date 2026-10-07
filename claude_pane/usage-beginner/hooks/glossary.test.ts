import { expect, test } from 'claude-code/testing'
import type { EngineInterface, ModelCompleteRequest } from 'claude-code'
import { clean } from './clean'
import { keyOf, parseTerms, quotaPaused } from './glossary'
import { extract, record, setKnown } from './register'

const ANSWER = 'SQLite mode=ro '.repeat(30)
const PATH = '/test/.usage/glossary.json'
const term = (name: string) => ({ term: name, plain: 'A simple explanation', example: 'A short example' })
const entry = (name: string, known = false) => ({ ...term(name), known, seen_count: 1, first_seen: 123 })
function fake(status?: string) {
  const files = new Map<string, string>()
  if (status !== undefined) files.set('/test/.claude/usage-status.json', status)
  const calls: ModelCompleteRequest[] = [], logs: string[] = []
  let response = { isAnswered: true, text: JSON.stringify([term('SQLite')]) } as unknown
  const $ = {
    env: { get: async () => '/test' },
    clock: { now: async () => 1000000 },
    fs: {
      exists: async (path: string) => files.has(path),
      read: async (path: string) => { if (!files.has(path)) throw new Error('Missing file'); return files.get(path)! },
      write: async (path: string, value: string) => { files.set(path, value) },
    },
    model: { complete: async (request: ModelCompleteRequest) => { calls.push(request); return response } },
    ui: { log: async (text: string) => { logs.push(text) } },
  } as unknown as EngineInterface
  return { $, files, calls, logs, reply: (value: unknown) => { response = value } }
}

test('fresh 90% quota prevents a model call', async () => {
  for (const used of [90, 100]) {
    const f = fake(JSON.stringify({ rate_limits: { five_hour: { used_percentage: used } }, _received_at_ts: 100 }))
    expect(await extract(f.$, ANSWER, 'zh-TW')).toEqual([])
    expect(f.calls.length).toBe(0)
  }
})
test('old, missing, unreadable and malformed quota permit a call', async () => {
  for (const status of [undefined, 'bad', '{}', JSON.stringify({ rate_limits: { five_hour: { used_percentage: 100 } }, _received_at_ts: 99 })]) {
    const f = fake(status)
    expect((await extract(f.$, ANSWER, 'en')).length).toBe(1)
    expect(f.calls.length).toBe(1)
  }
})
test('bad JSON and unanswered replies stay hidden and logged', async () => {
  for (const reply of [{ isAnswered: true, text: 'broken' }, { isAnswered: false, reason: 'empty-reply' }]) {
    const f = fake(); f.reply(reply)
    expect(await extract(f.$, ANSWER, 'en')).toEqual([])
    expect(f.files.has(PATH)).toBe(false)
    expect(f.logs.length).toBe(1)
  }
})
test('eight candidates exclude all recorded terms and show only three', async () => {
  const f = fake()
  f.files.set(PATH, JSON.stringify({ version: 1, terms: { sqlite: entry('SQLite', true), 'mode=ro': entry('mode=ro') } }))
  f.reply({ isAnswered: true, text: JSON.stringify([' SQLite ', 'MODE=RO', 'API', 'SDK', 'CLI', 'JSON', 'RPC', 'MCP'].map(term)) })
  expect((await extract(f.$, ANSWER, 'en')).map(row => row.term)).toEqual(['API', 'SDK', 'CLI'])
  const saved = JSON.parse(f.files.get(PATH)!)
  expect(saved.terms.api).toEqual({ ...term('API'), first_seen: 1000000, seen_count: 1, known: false })
  expect(saved.terms.sqlite.known).toBe(true)
})
test('all recorded candidates stay hidden', async () => {
  const f = fake()
  f.files.set(PATH, JSON.stringify({ version: 1, terms: { sqlite: entry('SQLite') } }))
  expect(await extract(f.$, ANSWER, 'en')).toEqual([])
})
test('clean removes escapes and invisible text, rejects tags and caps code points', () => {
  expect(clean('\x1b[31mSQLite\x1b[0m\u200b', 40)).toBe('SQLite')
  expect(clean('safe\u{E0061}hidden', 40)).toBe('')
  expect(clean('😀'.repeat(50), 40)).toBe('😀'.repeat(39) + '…')
  expect(parseTerms(JSON.stringify([{ term: 'T', plain: 'P', example: 'bad\u{E0061}' }]))).toEqual([])
  expect(parseTerms(JSON.stringify([{ term: '😀'.repeat(50), plain: 'P'.repeat(50), example: 'E'.repeat(90) }]))[0]).toEqual({ term: '😀'.repeat(39) + '…', plain: 'P'.repeat(39) + '…', example: 'E'.repeat(79) + '…' })
  expect(keyOf(' SQLite ')).toBe('sqlite')
})
test('parseTerms reads an array wrapped in a code fence or a sentence', () => {
  const row = { term: 'SQLite', plain: 'P', example: 'E' }
  expect(parseTerms('```json\n' + JSON.stringify([row]) + '\n```')).toEqual([row])
  expect(parseTerms('Here you go: ' + JSON.stringify([row]))).toEqual([row])
  expect(() => parseTerms('no array here')).toThrow()
})
test('marking all displayed terms known preserves other records; history toggles', async () => {
  const f = fake()
  await record(f.$, PATH, [term('SQLite'), term('API')])
  await setKnown(f.$, PATH, ['sqlite', 'api'], true)
  expect(Object.values(JSON.parse(f.files.get(PATH)!).terms).map(row => (row as { known: boolean }).known)).toEqual([true, true])
  await setKnown(f.$, PATH, ['api'])
  expect(JSON.parse(f.files.get(PATH)!).terms.api.known).toBe(false)
  expect(JSON.parse(f.files.get(PATH)!).terms.sqlite.known).toBe(true)
})
test('re-read merges a term another conversation wrote after the initial read', async () => {
  const f = fake()
  let reads = 0
  f.files.set(PATH, JSON.stringify({ version: 1, terms: {} }))
  const original = f.$.fs.read
  f.$.fs.read = (async (path: string) => {
    if (path === PATH && ++reads === 2) f.files.set(PATH, JSON.stringify({ version: 1, terms: { concurrent: entry('Concurrent') } }))
    return original(path)
  }) as EngineInterface['fs']['read']
  await extract(f.$, ANSWER, 'en')
  expect(Object.keys(JSON.parse(f.files.get(PATH)!).terms)).toEqual(['concurrent', 'sqlite'])
})
test('short answers never call the model; prompt contains only truncated answer', async () => {
  const f = fake()
  expect(await extract(f.$, 'x'.repeat(199), 'en')).toEqual([])
  expect(f.calls.length).toBe(0)
  await extract(f.$, 'x'.repeat(6500), 'ja')
  expect(f.calls[0]!.model).toBe('haiku')
  expect(f.calls[0]!.prompt).toBe('x'.repeat(6000))
  expect(f.calls[0]!.system).toContain('Use Japanese')
})
test('stale detached results are dropped, corrupt glossary is preserved', async () => {
  const f = fake()
  f.$.model.complete = async () => { active = false; return { isAnswered: true, text: JSON.stringify([term('API')]) } as never }
  let active = true
  expect(await extract(f.$, ANSWER, 'en', () => active)).toEqual([])
  expect(f.files.has(PATH)).toBe(false)
  const other = fake(); other.files.set(PATH, 'broken')
  expect(await extract(other.$, ANSWER, 'en')).toEqual([])
  expect(other.files.get(PATH)).toBe('broken')
  expect(other.logs.length).toBe(1)
})
test('quota rejects future timestamps and non-number fields', () => {
  expect(quotaPaused(JSON.stringify({ rate_limits: { five_hour: { used_percentage: '90' } }, _received_at_ts: 1000 }), 1000000)).toBe(false)
  expect(quotaPaused(JSON.stringify({ rate_limits: { five_hour: { used_percentage: 90 } }, _received_at_ts: 1001 }), 1000000)).toBe(false)
})
