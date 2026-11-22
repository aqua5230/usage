import { expect, test } from 'claude-code/testing'
import type { EngineInterface, ModelCompleteRequest } from 'claude-code'
import { clean } from './clean'
import { graded, hidden, isIdentifier, keyOf, parseTerms, quizOf, quotaPaused, userTyped, withKnown } from './glossary'
import type { Glossary } from './glossary'
import { extract, grade, record, setKnown } from './register'
import { readGlossary, updateGlossary } from './storage'

const ANSWER = 'SQLite mode=ro '.repeat(30)
const PATH = '/test/.usage/glossary.json'
const DAY = 86_400_000
const term = (name: string) => ({ term: name, plain: 'A simple explanation', example: 'A short example' })
const entry = (name: string, known = false) => ({ ...term(name), known, seen_count: 1, first_seen: 123 })

test('typed terms use ASCII word boundaries, normalization and CJK substrings', () => {
  for (const text of ['PR搞定', 'open a PR', ' pr ', 'improper PR']) expect(userTyped(' PR ', text)).toBe(true)
  for (const text of ['decision', 'CI_job', 'job_CI', 'CI2', '2CI']) expect(userTyped('CI', text)).toBe(false)
  expect(userTyped('分支', '把分支合併')).toBe(true)
  expect(userTyped('mode=ro', 'use MODE=RO')).toBe(true)
  expect(userTyped('C++', 'use C++')).toBe(true)
  expect(userTyped('C++', 'C++17')).toBe(false)
  expect(userTyped('a', 'a')).toBe(false)
  expect(userTyped('字', '文字')).toBe(false)
  expect(userTyped('PR', 'PR' + ' '.repeat(498))).toBe(true)
  expect(userTyped('PR', 'PR' + ' '.repeat(499))).toBe(false)
})

test('typed entries stay hidden, are not quizzed, and forgetting clears the marker', () => {
  const row = { ...entry('API'), user_typed_at: 0, review_at: 1, reviews: 0 }
  expect(hidden(row, 100 * DAY)).toBe(true)
  expect(quizOf({ version: 1, terms: { api: row, other: entry('other') } }, 100 * DAY, () => 0)).toBeUndefined()
  expect(withKnown(row, false, 100 * DAY)).toEqual(entry('API'))
  expect(hidden(withKnown(row, false, 100 * DAY), 100 * DAY)).toBe(false)
  expect(withKnown(row, true, 100 * DAY).user_typed_at).toBe(0)
})

test('readGlossary preserves valid typed timestamps and rejects invalid values', async () => {
  const f = fake()
  for (const user_typed_at of [0, 123.5]) {
    f.files.set(PATH, JSON.stringify({ version: 1, terms: { api: { ...entry('API'), user_typed_at } } }))
    expect((await readGlossary(f.$, PATH)).terms.api!.user_typed_at).toBe(user_typed_at)
    await setKnown(f.$, PATH, ['api'], false)
    expect(JSON.parse(f.files.get(PATH)!).terms.api.user_typed_at).toBeUndefined()
  }
  for (const user_typed_at of ['123', null, true, {}, -1]) {
    f.files.set(PATH, JSON.stringify({ version: 1, terms: { api: { ...entry('API'), user_typed_at } } }))
    await expect(readGlossary(f.$, PATH)).rejects.toThrow('Invalid glossary entry')
  }
  f.files.set(PATH, '{"version":1,"terms":{"api":{"term":"API","plain":"p","example":"e","known":false,"seen_count":1,"first_seen":0,"user_typed_at":1e400}}}')
  await expect(readGlossary(f.$, PATH)).rejects.toThrow('Invalid glossary entry')
})

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
  expect((await extract(f.$, ANSWER + 'JSON API SDK CLI RPC MCP', 'en')).map(row => row.term)).toEqual(['MODE=RO', 'API', 'SDK'])
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
test('identifier filtering keeps terms with context and key=value parameters', () => {
  for (const name of ['feat/example', 'origin/main', 'app.js', 'hooks/', '/tmp/settings', '#395', '８５９１ ± ½', 'register.tsx', 'v2.1.330-rc.1', 'deadBEEF', 'https://example.com/a?q=1']) {
    expect(isIdentifier(name)).toBe(true)
  }
  for (const name of ['HTTP 404', 'mode=ro', '--config=src/settings.json', '合併請求', '/compact', 'CI/CD', 'I/O', 'async/await', 'Node.js']) {
    expect(isIdentifier(name)).toBe(false)
  }
})
test('only terms in the excerpt sent to Haiku fill the three slots', async () => {
  const f = fake()
  const excerpt = 'Use feat/example, #395, 8591, a 分支, HTTP 404 and mode=ro. '.padEnd(6000, 'x')
  const candidates = ['feat/example', '#395', '8591', 'SQLite', 'SDK', '分支', 'http 404', 'MODE=RO', 'HTTP']
  f.reply({ isAnswered: true, text: JSON.stringify(candidates.map(term)) })
  expect((await extract(f.$, excerpt + ' SDK', 'en')).map(row => row.term)).toEqual(['分支', 'http 404', 'MODE=RO'])
  expect(Object.keys(JSON.parse(f.files.get(PATH)!).terms)).toEqual(['分支', 'http 404', 'mode=ro'])
})
test('grounding checks the original term before truncating it for display and storage', async () => {
  const f = fake()
  const name = '複'.repeat(40) + '雜'
  const shortened = '複'.repeat(39) + '…'
  f.reply({ isAnswered: true, text: JSON.stringify([term(name)]) })
  expect(await extract(f.$, shortened.repeat(10), 'en')).toEqual([])
  expect(await extract(f.$, name.repeat(10), 'en')).toEqual([term(shortened)])
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
  const sourceTerm = '😀'.repeat(50)
  expect(parseTerms(JSON.stringify([{ term: sourceTerm, plain: 'P'.repeat(50), example: 'E'.repeat(90) }]))[0]).toEqual({ sourceTerm, term: '😀'.repeat(39) + '…', plain: 'P'.repeat(39) + '…', example: 'E'.repeat(79) + '…' })
  expect(keyOf(' SQLite ')).toBe('sqlite')
})
test('parseTerms reads a whole JSON array and caps it at eight terms', () => {
  const rows = Array.from({ length: 9 }, (_, index) => term('Term ' + index))
  expect(parseTerms(JSON.stringify(rows))).toEqual(rows.slice(0, 8).map(row => ({ ...row, sourceTerm: row.term })))
  expect(parseTerms('[]')).toEqual([])
})
test('parseTerms prefers a JSON code block to an array in the surrounding prose', () => {
  const row = term('SQLite')
  const prose = JSON.stringify([term('Other')])
  expect(parseTerms(prose + '\n```json\n' + JSON.stringify([row]) + '\n```')).toEqual([{ ...row, sourceTerm: row.term }])
})
test('parseTerms finds a complete validated array among other brackets', () => {
  const row = { ...term('SQLite'), example: 'Use "[x]" with \\[ and \\" ]' }
  const list = JSON.stringify([{ ...row, extra: [1, [2]] }])
  expect(parseTerms('note [not JSON] ["not a term"] [] [unclosed ' + list + '\n[appendix]')).toEqual([{ ...row, sourceTerm: row.term }])
  expect(parseTerms('no terms: []')).toEqual([])
  expect(() => parseTerms('no array here')).toThrow()
  expect(() => parseTerms('[{"term":"SQLite","plain":"P","exam')).toThrow()
  expect(() => parseTerms('note [{"term":"missing fields"}]')).toThrow()
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
test('extraction filters and merges using changes made after the preflight read', async () => {
  const f = fake()
  let reads = 0
  const sqlite = { ...entry('SQLite', true), reviews: 1, review_at: 1000 }
  f.files.set(PATH, JSON.stringify({ version: 1, terms: { sqlite: entry('SQLite') } }))
  f.reply({ isAnswered: true, text: JSON.stringify(['SQLite', 'mode=ro'].map(term)) })
  const original = f.$.fs.read
  f.$.fs.read = (async (path: string) => {
    if (path === PATH && ++reads === 2) {
      f.files.set(PATH, JSON.stringify({ version: 1, terms: { sqlite, concurrent: entry('Concurrent') } }))
    }
    return original(path)
  }) as EngineInterface['fs']['read']
  expect(await extract(f.$, ANSWER, 'en')).toEqual([term('mode=ro')])
  const saved = JSON.parse(f.files.get(PATH)!).terms
  expect(Object.keys(saved)).toEqual(['sqlite', 'concurrent', 'mode=ro'])
  expect(saved.sqlite).toEqual(sqlite)
})
test('two writers apply their prepared changes to the latest glossary in sequence', async () => {
  const f = fake(), other = { ...f.$ }
  f.files.set(PATH, JSON.stringify({ version: 1, terms: { api: entry('API') } }))
  const markApi = (data: Glossary) => {
    data.terms.api = withKnown(data.terms.api!, true, 0)
    return true
  }
  const ci = entry('CI')
  const addCi = (data: Glossary) => {
    data.terms.ci = ci
    return true
  }
  await updateGlossary(f.$, PATH, markApi)
  await updateGlossary(other, PATH, addCi)
  const saved = JSON.parse(f.files.get(PATH)!)
  expect(saved.terms.api.known).toBe(true)
  expect(saved.terms.ci).toEqual(ci)
})
test('short answers never call the model; prompt frames only the truncated answer', async () => {
  const f = fake()
  expect(await extract(f.$, 'x'.repeat(199), 'en')).toEqual([])
  expect(f.calls.length).toBe(0)
  await extract(f.$, 'x'.repeat(6500), 'ja')
  expect(f.calls[0]!.model).toBe('haiku')
  expect(f.calls[0]!.prompt).toBe(`<answer>\n${'x'.repeat(6000)}\n</answer>\n\nList the terms from the answer above. Return ONLY the JSON array.`)
  expect(f.calls[0]!.system).toContain('Use Japanese')
  expect(f.calls[0]!.system).toContain('at most 8 objects')
  expect(f.calls[0]!.system).toContain('concepts that also apply to other projects')
})
test('stale detached results are dropped', async () => {
  const f = fake()
  f.$.model.complete = async () => { active = false; return { isAnswered: true, text: JSON.stringify([term('API')]) } as never }
  let active = true
  expect(await extract(f.$, ANSWER, 'en', () => active)).toEqual([])
  expect(f.files.has(PATH)).toBe(false)
})
test('a corrupt glossary blocks Haiku, caches its validation error and recovers after a repair', async () => {
  const f = fake(), valid = '{"version":1,"terms":{}}', broken = 'x'.repeat(valid.length)
  f.files.set(PATH, broken)
  const error = await readGlossary(f.$, PATH).catch((error: unknown) => error)
  expect(error).toBeInstanceOf(SyntaxError)
  expect(await readGlossary(f.$, PATH).catch((error: unknown) => error)).toBe(error)
  for (let i = 0; i < 2; i++) expect(await extract(f.$, ANSWER, 'en')).toEqual([])
  expect(f.calls.length).toBe(0)
  expect(f.files.get(PATH)).toBe(broken)
  expect(f.logs.length).toBeGreaterThan(0)
  await expect(setKnown(f.$, PATH, ['sqlite'], true)).rejects.toThrow()
  expect(f.files.get(PATH)).toBe(broken)
  f.files.set(PATH, valid)
  expect(await extract(f.$, ANSWER, 'en')).toEqual([term('SQLite')])
  expect(f.calls.length).toBe(1)
})
test('an unreadable glossary blocks Haiku and only logs the failure', async () => {
  const f = fake()
  f.$.fs.exists = async path => path === PATH
  expect(await extract(f.$, ANSWER, 'en')).toEqual([])
  expect(f.calls.length).toBe(0)
  expect(f.files.has(PATH)).toBe(false)
  expect(f.logs[0]).toContain('Missing file')
})
test('quota rejects future timestamps and non-number fields', () => {
  expect(quotaPaused(JSON.stringify({ rate_limits: { five_hour: { used_percentage: '90' } }, _received_at_ts: 1000 }), 1000000)).toBe(false)
  expect(quotaPaused(JSON.stringify({ rate_limits: { five_hour: { used_percentage: 90 } }, _received_at_ts: 1001 }), 1000000)).toBe(false)
})
test('five-hour quota uses its observation time and pauses only until its reset', () => {
  const now = 10_000
  const paused = (used: number, observed?: number, reset?: number, received = now) => quotaPaused(JSON.stringify({
    rate_limits: { five_hour: { used_percentage: used, resets_at: reset } },
    _received_at_ts: received,
    _rate_limits_observed_at: { five_hour: observed, seven_day: now },
  }), now * 1000)
  expect(paused(95, now - 1200, now + 300, now - 1200)).toBe(true)
  expect(paused(95, now - 1200, now + 300)).toBe(true)
  expect(paused(95, now - 1200)).toBe(false)
  expect(paused(95, now - 1200, now)).toBe(false)
  expect(paused(95, now - 1200, now - 20)).toBe(false)
  expect(paused(89, now - 1, now + 300)).toBe(false)
  expect(paused(95, now + 1, now + 300)).toBe(false)
  expect(paused(95, undefined, now + 300)).toBe(false)
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
  expect(quizOf({ ...data, terms: { ...data.terms, commit: { ...data.terms.commit!, user_typed_at: 1 } } }, 6, () => 0)?.key).not.toBe('commit')
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
