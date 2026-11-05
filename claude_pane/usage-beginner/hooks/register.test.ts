import { expect, test } from 'claude-code/testing'
import type { RenderPropsOf } from 'claude-code'

const normalizePath = (path: string) => path.replaceAll('\\','/').replace(/^[A-Za-z]:/, '')
const band: RenderPropsOf['AbovePrompt'] = {
  isWorking: false, hasSurvey: false, maxRows: 20, bodyColumns: 100,
  scroll: { offset: 0, bodyRows: 20 }, view: {},
}
// turn.start stamps typed terms in the background; let that work finish before checking.
const settle = () => new Promise(resolve => setTimeout(resolve, 10))

test('main turn stamps typed entries once, reads once and writes only changes', async ($, on) => {
  const path = '/test/.usage/glossary.json'
  const row = (term: string) => ({ term, plain: 'p', example: 'e', known: false, first_seen: 0, seen_count: 1 })
  let data = JSON.stringify({ version: 1, terms: { pr: row('PR'), ci: row('CI'), '分支': row('分支') } })
  let reads = 0, writes = 0, now = 123
  on('env.get', () => ({ value: '/test' }))
  on('clock.now', () => ({ value: now }))
  on('fs.exists', () => ({ value: true }))
  on('fs.read', (_$, e) => { expect(normalizePath(e.path)).toBe(path); reads++; return { value: data } })
  on('fs.write', (_$, e) => { expect(normalizePath(e.path)).toBe(path); writes++; data = e.text; return { value: undefined } })
  on('turn.start', (_$, e) => ({ turnId: e.turnId }))
  await $.turn.start({ text: 'PR搞定，把分支合併 decision', turnId: 'one' })
  await settle()
  expect(reads).toBe(1)
  expect(writes).toBe(1)
  expect(JSON.parse(data).terms.pr.user_typed_at).toBe(123)
  expect(JSON.parse(data).terms['分支'].user_typed_at).toBe(123)
  expect(JSON.parse(data).terms.ci.user_typed_at).toBeUndefined()
  now = 456
  await $.turn.start({ text: 'open a PR', turnId: 'two' })
  await settle()
  expect(reads).toBe(2)
  expect(writes).toBe(1)
  expect(JSON.parse(data).terms.pr.user_typed_at).toBe(123)
  await $.turn.start({ text: 'CI', turnId: 'sub', agentId: 'agent-1' })
  await $.turn.start({ text: 'CI' + ' '.repeat(499), turnId: 'paste' })
  await $.turn.start({ text: '', turnId: 'continuation' })
  await $.turn.start({ text: 'CI 是什麼？', turnId: 'question' })
  await settle()
  expect(reads).toBe(2)
  expect(writes).toBe(1)
})

test('turn start logs read and write failures and still calls next', async ($, on) => {
  let brokenRead = true, nextCalls = 0
  const logs: string[] = []
  on('env.get', () => ({ value: '/test' }))
  on('clock.now', () => ({ value: 123 }))
  on('fs.exists', () => ({ value: true }))
  on('fs.read', () => {
    if (brokenRead) throw new Error('read failed')
    return { value: JSON.stringify({ version: 1, terms: { pr: { term: 'PR', plain: 'p', example: 'e', known: false, first_seen: 0, seen_count: 1 } } }) }
  })
  on('fs.write', () => { throw new Error('write failed') })
  on('ui.log', (_$, e) => { logs.push(e.text); return { value: undefined } })
  on('turn.start', (_$, e) => { nextCalls++; return { turnId: e.turnId } })
  expect((await $.turn.start({ text: 'PR', turnId: 'read' })).turnId).toBe('read')
  await settle()
  brokenRead = false
  expect((await $.turn.start({ text: 'PR', turnId: 'write' })).turnId).toBe('write')
  await settle()
  expect(nextCalls).toBe(2)
  expect(logs[0]).toContain('fs.read')
  expect(logs[1]).toContain('fs.write')
})

test('extraction drops current typed candidates, ignores subagents and resets on the next turn', async ($, on) => {
  const path = '/test/.usage/glossary.json'
  let data = '{"version":1,"terms":{}}'
  on('env.get', () => ({ value: '/test' }))
  on('clock.now', () => ({ value: 1000000 }))
  on('fs.exists', (_$, e) => ({ value: normalizePath(e.path) === path }))
  on('fs.read', (_$, e) => ({ value: normalizePath(e.path) === path ? data : '{}' }))
  on('fs.write', (_$, e) => { data = e.text; return { value: undefined } })
  on('model.complete', () => ({ value: { isAnswered: true, text: JSON.stringify(['PR', 'API'].map(term => ({ term, plain: 'p', example: 'e' }))), usage: { input_tokens: 0, output_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 } } }))
  on('turn.start', (_$, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: 'finished' }))
  on('ui.render', () => ({ type: 'Box', props: {}, children: [] }))
  const ui = await $.ui.mount({ plugin: 'usage-beginner', surface: 'terminal', component: 'AbovePrompt', props: band })
  for (const [turnId, text] of [['typed', 'open a PR'], ['continuation', ''], ['paste', 'PR' + ' '.repeat(499)]]) {
    data = '{"version":1,"terms":{}}'
    await $.turn.start({ text: text!, turnId: turnId! })
    await $.turn.start({ text: 'API', turnId: 'sub', agentId: 'agent-1' })
    await $.turn.complete({ reason: 'answer', answer: 'PR API '.repeat(40), durationMs: 1, isAborted: false, turnId: turnId! })
    for (let i = 0; i < 30 && !(await ui.find({ key: 'example-0' })); i++) await ui.redraw()
    expect(await ui.find({ key: 'example-0' })).toBeDefined()
    expect(Object.keys(JSON.parse(data).terms)).toEqual(turnId === 'typed' ? ['api'] : ['pr', 'api'])
  }
})

test('examples, hidden bands, and pressing 9 updates glossary', async ($, on) => {
  const trace: string[] = []
  const files = new Map<string, string>()
  on('env.get', (_$, e) => ({ value: e.name === 'HOME' ? '/test' : e.name === 'OS' ? 'Linux' : undefined }))
  on('clock.now', () => ({ value: 1000000 }))
  on('fs.exists', (_$, e) => ({ value: files.has(normalizePath(e.path)) }))
  on('fs.read', (_$, e) => ({ value: files.get(normalizePath(e.path)) ?? '{}' }))
  on('ui.log', (_$, e) => { trace.push(JSON.stringify(e)); return { value: undefined } })
  on('model.complete', async (_$, e) => {
    expect(e.model).toBe('haiku')
    return { value: { isAnswered: true, text: '[{"term":"SQLite","plain":"A file database","example":"data.sqlite"}]', usage: { input_tokens: 0, output_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 } } }
  })
  on('fs.write', (_$, e) => { files.set(normalizePath(e.path), e.text); return { value: undefined } })
  on('ui.render', () => ({ type: 'Box', props: {}, children: [] }))
  on('turn.start', (_$, e) => ({ turnId: e.turnId }))
  on('ui.open', (_$, e) => { expect(e.title).toBe('Term history'); return { value: { isPlaced: true } } })
  on('turn.complete', () => ({ text: 'original' }))
  const result = await $.turn.complete({ reason: 'answer', answer: 'SQLite '.repeat(40), durationMs: 1, isAborted: false, turnId: 'one' })
  expect(result.text).toBe('original')
  const ui = await $.ui.mount({ plugin: 'usage-beginner', surface: 'terminal', component: 'AbovePrompt', props: band })
  for (let i = 0; i < 30 && !(await ui.find({ key: 'example-0' })); i++) await ui.redraw()
  if (!(await ui.find({ key: 'example-0' }))) throw new Error(JSON.stringify(trace))
  expect((await ui.find({ key: 'example-0' }))?.text).toContain('SQLite')
  expect(await ui.find({ text: 'data.sqlite' })).toBeUndefined()
  await ui.press({ key: 'example-0' })
  expect(await ui.find({ text: 'data.sqlite' })).toBeDefined()
  await ui.press({ key: 'example-0' })
  expect(await ui.find({ text: 'data.sqlite' })).toBeUndefined()
  await ui.redraw({ ...band, isWorking: true })
  expect(await ui.find({ key: 'all-known' })).toBeUndefined()
  await ui.redraw({ ...band, hasSurvey: true })
  expect(await ui.find({ key: 'all-known' })).toBeUndefined()
  await ui.redraw(band)
  const button = await ui.find({ key: 'all-known' })
  expect(button).toBeDefined()
  await ui.press({ key: 'all-known' })
  expect(JSON.parse(files.get('/test/.usage/glossary.json')!).terms.sqlite.known).toBe(true)
  expect(await ui.find({ key: 'all-known' })).toBeUndefined()
  expect((await $.command.run({ command: 'terms', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 100 } })).text).toBe('Term history opened.')
  const history = await $.ui.mount({
    plugin: 'usage-beginner', surface: 'terminal', component: 'Pane', requestId: 'usage-beginner-terms',
    props: { title: 'Term history', isFocused: true, bodyColumns: 100, placement: 'dock', scroll: { offset: 0, bodyRows: 20 }, view: {} },
  })
  expect(await history.find({ text: 'data.sqlite' })).toBeDefined()
  expect((await history.find({ key: 'known-sqlite' }))?.text).toBe('Not yet understood')
  await history.press({ key: 'known-sqlite' })
  expect(JSON.parse(files.get('/test/.usage/glossary.json')!).terms.sqlite.known).toBe(false)
  // Reset only the in-memory fixture to exercise both ways of hiding tips.
  files.set('/test/.usage/glossary.json', '{"version":1,"terms":{}}')
  await $.turn.complete({ reason: 'answer', answer: 'SQLite '.repeat(40), durationMs: 1, isAborted: false, turnId: 'two' })
  for (let i = 0; i < 30 && !(await ui.find({ key: 'example-0' })); i++) await ui.redraw()
  await ui.press({ key: 'dismiss' })
  expect(await ui.find({ key: 'example-0' })).toBeUndefined()
  expect(JSON.parse(files.get('/test/.usage/glossary.json')!).terms.sqlite.known).toBe(false)
  files.set('/test/.usage/glossary.json', '{"version":1,"terms":{}}')
  await $.turn.complete({ reason: 'answer', answer: 'SQLite '.repeat(40), durationMs: 1, isAborted: false, turnId: 'three' })
  for (let i = 0; i < 30 && !(await ui.find({ key: 'example-0' })); i++) await ui.redraw()
  await $.turn.start({ text: 'Subagent task', turnId: 'sub', agentId: 'agent-1' })
  await ui.redraw()
  expect(await ui.find({ key: 'example-0' })).toBeDefined()
  await $.turn.start({ text: 'Next task', turnId: 'four' })
  expect(await ui.find({ key: 'example-0' })).toBeUndefined()
})

test('turn completion returns before a slow model reply', async ($, on) => {
  let release: () => void = () => {}, saved: () => void = () => {}, wrote = false
  const waiting = new Promise<void>(resolve => { release = resolve })
  const stored = new Promise<void>(resolve => { saved = resolve })
  on('env.get', () => ({ value: '/test' }))
  on('clock.now', () => ({ value: 1000000 }))
  on('fs.exists', () => ({ value: false }))
  on('fs.read', () => ({ value: '{}' }))
  on('fs.write', () => { wrote = true; saved(); return { value: undefined } })
  on('model.complete', async () => {
    await waiting
    return { value: { isAnswered: true, text: '[{"term":"API","plain":"A program interface","example":"get()"}]', usage: { input_tokens: 0, output_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 } } }
  })
  on('turn.complete', () => ({ text: 'finished' }))
  expect((await $.turn.complete({ reason: 'answer', answer: 'API '.repeat(100), durationMs: 1, isAborted: false, turnId: 'slow' })).text).toBe('finished')
  expect(wrote).toBe(false)
  release()
  await stored
})

test('the answer is framed as data, and a reply with no array logs what Haiku said', async ($, on) => {
  const logs: string[] = []
  let logged: () => void = () => {}
  const done = new Promise<void>(resolve => { logged = resolve })
  on('env.get', () => ({ value: '/test' }))
  on('clock.now', () => ({ value: 1000000 }))
  on('fs.exists', () => ({ value: false }))
  on('fs.read', () => ({ value: '{}' }))
  on('ui.log', (_$, e) => { logs.push(e.text); logged(); return { value: undefined } })
  on('model.complete', async (_$, e) => {
    expect(e.prompt).toContain('<answer>\nWant me to rebase now? ')
    expect(e.prompt).toMatch(/<\/answer>\n\nList the terms from the answer above\. Return ONLY the JSON array\.$/)
    expect(e.maxTokens).toBe(2048)
    return { value: { isAnswered: true, text: 'Sure, I can rebase it for you.', usage: { input_tokens: 0, output_tokens: 9, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 } } }
  })
  on('turn.complete', () => ({ text: 'finished' }))
  await $.turn.complete({ reason: 'answer', answer: 'Want me to rebase now? '.repeat(10), durationMs: 1, isAborted: false, turnId: 'prose' })
  await done
  expect(logs[0]).toContain('Expected a JSON array (30 chars, 9 tokens): "Sure, I can rebase it for you."')
})

test('a new conversation draws the day\'s quiz once and grades the answer', async ($, on) => {
  const DAY = 86_400_000, path = '/test/.usage/glossary.json'
  const row = (term: string, plain: string, known: boolean) =>
    ({ term, plain, example: 'e', first_seen: 1, seen_count: 1, known, ...(known ? { review_at: 2, reviews: 0 } : {}) })
  const files = new Map([[path, JSON.stringify({ version: 1, terms: { push: row('push', 'Upload commits', true), merge: row('merge', 'Join two branches', false) } })]])
  on('env.get', () => ({ value: '/test' }))
  on('clock.now', () => ({ value: 10 * DAY }))
  on('fs.exists', (_$, e) => ({ value: files.has(normalizePath(e.path)) }))
  on('fs.read', (_$, e) => ({ value: files.get(normalizePath(e.path)) ?? '{}' }))
  on('fs.write', (_$, e) => { files.set(normalizePath(e.path), e.text); return { value: undefined } })
  on('command.register', (_$, e) => ({ value: { command: e.name } }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('ui.render', () => ({ type: 'Box', props: {}, children: [] }))
  await $.session.start({ cwd: '/test', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ plugin: 'usage-beginner', surface: 'terminal', component: 'AbovePrompt', props: band })
  expect(await ui.find({ text: 'What does push mean?' })).toBeDefined()
  for (let i = 0; i < 30 && JSON.parse(files.get(path)!).quizzed_at === undefined; i++) await ui.redraw()
  expect(JSON.parse(files.get(path)!).quizzed_at).toBe(10 * DAY)
  const right = (await ui.find({ key: 'quiz-0' }))?.text?.includes('Upload commits') ? 'quiz-0' : 'quiz-1'
  await ui.press({ key: right })
  for (let i = 0; i < 30 && !(await ui.find({ text: 'Correct! Next quiz in 21 days.' })); i++) await ui.redraw()
  expect(await ui.find({ text: 'Correct! Next quiz in 21 days.' })).toBeDefined()
  expect(JSON.parse(files.get(path)!).terms.push).toEqual({ ...row('push', 'Upload commits', true), review_at: 31 * DAY, reviews: 1 })
  await ui.press({ key: 'quiz-close' })
  expect(await ui.find({ key: 'quiz-close' })).toBeUndefined()
})
