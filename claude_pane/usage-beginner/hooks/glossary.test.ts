import { expect, test } from 'claude-code/testing'
import type { EngineInterface, ModelCompleteRequest } from 'claude-code'
import { clean } from './clean'
import { graded, hidden, keyOf, parseTerms, quizOf, quotaPaused, withKnown } from './glossary'
import { extract, grade, readGlossary, record, setKnown } from './register'

const ANSWER = 'SQLite mode=ro '.repeat(30)
const PATH = '/test/.usage/glossary.json'
const DAY = 86_400_000
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
test('eight candidates exclude understood and cooling terms, bring back cooled ones and show only three', async () => {
  const f = fake(), now = 2 * DAY
  f.$.clock.now = async () => now
  f.files.set(PATH, JSON.stringify({ version: 1, terms: {
    sqlite: entry('SQLite', true), 'mode=ro': entry('mode=ro'), json: { ...entry('JSON'), last_seen: DAY + 1 },
  } }))
  f.reply({ isAnswered: true, text: JSON.stringify([' SQLite ', 'MODE=RO', 'JSON', 'API', 'SDK', 'CLI', 'RPC', 'MCP'].map(term)) })
  expect((await extract(f.$, ANSWER, 'en')).map(row => row.term)).toEqual(['MODE=RO', 'API', 'SDK'])
  const saved = JSON.parse(f.files.get(PATH)!)
  expect(saved.terms.api).toEqual({ ...term('API'), first_seen: now, last_seen: now, seen_count: 1, known: false })
  expect(saved.terms['mode=ro']).toEqual({ ...entry('mode=ro'), last_seen: now, seen_count: 2 })
  expect(saved.terms.sqlite.known).toBe(true)
})
test('understood and cooling candidates stay hidden', async () => {
  const f = fake()
  f.files.set(PATH, JSON.stringify({ version: 1, terms: { sqlite: entry('SQLite', true) } }))
  expect(await extract(f.$, ANSWER, 'en')).toEqual([])
  f.files.set(PATH, JSON.stringify({ version: 1, terms: { sqlite: entry('SQLite') } }))
  expect(await extract(f.$, ANSWER, 'en')).toEqual([])
})
test('cooldown grows from 1 to 3 to 7 days and never ends for understood terms', () => {
  const row = (seen_count: number, last_seen?: number) => ({ ...entry('T'), first_seen: 0, seen_count, ...(last_seen === undefined ? {} : { last_seen }) })
  for (const [seen, days] of [[1, 1], [2, 3], [3, 7], [9, 7]] as const) {
    expect(hidden(row(seen), days * DAY - 1)).toBe(true)
    expect(hidden(row(seen), days * DAY)).toBe(false)
  }
  expect(hidden(row(1, DAY), 2 * DAY - 1)).toBe(true)
  expect(hidden(row(1, DAY), 2 * DAY)).toBe(false)
  expect(hidden({ ...row(1), known: true }, 100 * DAY)).toBe(true)
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
  expect(() => parseTerms('[{"term":"SQLite","plain":"P","exam')).toThrow()
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
test('short answers never call the model; prompt frames only the truncated answer', async () => {
  const f = fake()
  expect(await extract(f.$, 'x'.repeat(199), 'en')).toEqual([])
  expect(f.calls.length).toBe(0)
  await extract(f.$, 'x'.repeat(6500), 'ja')
  expect(f.calls[0]!.model).toBe('haiku')
  expect(f.calls[0]!.prompt).toBe(`<answer>\n${'x'.repeat(6000)}\n</answer>\n\nList the terms from the answer above. Return ONLY the JSON array.`)
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

const learned = (name: string, plain: string, review_at?: number) =>
  ({ ...entry(name, true), plain, ...(review_at === undefined ? {} : { review_at, reviews: 0 }) })
test('quiz picks the longest-waiting due term, masks it, and skips overlapping or revealing distractors', () => {
  const data = { version: 1 as const, terms: {
    push: learned('push', 'Send your PUSH-ed commits to the remote', 5),
    commit: learned('commit', 'A saved snapshot', 3),
    'git commit': entry('git commit'),
    branch: { ...entry('branch'), plain: 'A line of work' },
    '分支 (branch)': { ...entry('分支 (branch)'), plain: 'Another line of work' },
    tag: { ...entry('tag'), plain: 'A commit label' },
    merge: { ...entry('merge'), plain: 'Join two branches' },
    later: learned('later', 'Not due yet', 10),
  } }
  const quiz = quizOf(data, 6, () => 0)!
  expect(quiz.key).toBe('commit')
  expect(quiz.options[quiz.answer]).toBe('A saved snapshot')
  expect(quiz.options.length).toBe(4)
  // "push" and "tag" explanations name "commit"; "git commit" overlaps the name.
  expect(quiz.options.some(o => o.includes('Send') || o.includes('label') || o.includes('A simple explanation'))).toBe(false)
  const pushQuiz = quizOf({ version: 1, terms: { push: data.terms.push, merge: data.terms.merge } }, 6, () => 0)!
  expect(pushQuiz.options[pushQuiz.answer]).toBe('Send your ___-ed commits to the remote')
  expect(quizOf({ ...data, quizzed_at: 6 - DAY + 1 }, 6, () => 0)).toBeUndefined()
  expect(quizOf({ ...data, quizzed_at: 6 - DAY }, 6, () => 0)?.key).toBe('commit')
  expect(quizOf({ version: 1, terms: { commit: data.terms.commit } }, 6, () => 0)).toBeUndefined()
  expect(quizOf({ version: 1, terms: { later: data.terms.later, merge: data.terms.merge } }, 6, () => 0)).toBeUndefined()
})
test('understanding schedules a 7-day quiz; right answers move it to 21, 60, then none; a wrong one forgets it', () => {
  const known = withKnown(entry('API'), true, 0)
  expect(known).toEqual({ ...entry('API', true), review_at: 7 * DAY, reviews: 0 })
  expect(withKnown(known, false, 0)).toEqual(entry('API'))
  const once = graded(known, true, 10)
  expect(once).toEqual({ ...known, reviews: 1, review_at: 10 + 21 * DAY })
  const twice = graded(once, true, 20)
  expect(twice.review_at).toBe(20 + 60 * DAY)
  const done = graded(twice, true, 30)
  expect(done.reviews).toBe(3)
  expect('review_at' in done).toBe(false)
  expect(graded(twice, false, 30)).toEqual(entry('API'))
})
test('quiz fields survive other writers, the history toggle schedules a quiz, and grading re-reads', async () => {
  const f = fake()
  f.files.set(PATH, JSON.stringify({ version: 1, quizzed_at: 5, terms: { push: { ...entry('push', true), review_at: 9, reviews: 1 }, sqlite: entry('SQLite') } }))
  f.$.clock.now = async () => 2 * DAY
  await record(f.$, PATH, [term('API')])
  let saved = JSON.parse(f.files.get(PATH)!)
  expect(saved.quizzed_at).toBe(5)
  expect(saved.terms.push).toEqual({ ...entry('push', true), review_at: 9, reviews: 1 })
  await setKnown(f.$, PATH, ['sqlite'])
  saved = JSON.parse(f.files.get(PATH)!)
  expect(saved.terms.sqlite).toEqual({ ...entry('SQLite', true), review_at: 9 * DAY, reviews: 0 })
  expect((await grade(f.$, PATH, 'api', true))).toBeUndefined()
  expect((await grade(f.$, PATH, 'push', false))?.known).toBe(false)
  expect(JSON.parse(f.files.get(PATH)!).terms.push).toEqual(entry('push'))
  f.files.set(PATH, JSON.stringify({ version: 1, quizzed_at: -1, terms: {} }))
  await expect(readGlossary(f.$, PATH)).rejects.toThrow()
})
