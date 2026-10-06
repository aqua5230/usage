import { configure } from './strings'
import type { AgentInfo } from 'claude-code'
import { expect, test } from 'claude-code/testing'
import { contextPercent, contextColor, parseContext, parseMix, mixLabel, staleContext, completedAgo, isWaiting, visibleAgents, backgroundCount, visibleRuns } from './display'
test('context 百分比單位、缺值與三種顏色門檻', () => {
  expect(contextPercent(undefined)).toBeUndefined()
  expect(contextPercent(0.41)).toBe(0)
  expect(contextPercent(0.9)).toBe(1)
  expect(contextPercent(41.6)).toBe(42)
  expect([0,49,50,79,80,100].map(percent => contextColor(percent))).toEqual([undefined,undefined,'yellow','yellow','red','red'])
  expect(parseContext('broken')).toBeNull()
  expect(parseContext('{"sessionId":"one","updatedAt":0}')).toEqual({sessionId:'one',updatedAt:0})
  expect(parseContext('{"sessionId":"one","percent":41,"updatedAt":0}')).toEqual({sessionId:'one',percent:41,updatedAt:0})
})
test('live 清掃只移除超過一天且已關閉的對話', () => {
  const open = new Set(['one'])
  expect(staleContext('one',0,open,86400001)).toBe(false)
  expect(staleContext('two',0,open,86400000)).toBe(false)
  expect(staleContext('two',0,open,86399999)).toBe(false)
  expect(staleContext('two',0,open,86400001)).toBe(true)
})
test('工作完成時間、失敗與未來時間', () => {
  expect(completedAgo({end:null,status:'running'},180000)).toBe('')
  expect(completedAgo({end:0,status:'completed'},59000)).toBe(' · just now · completed')
  expect(completedAgo({end:0,status:'completed'},60000)).toBe(' · 1m ago · completed')
  expect(completedAgo({end:0,status:'completed'},180000)).toBe(' · 3m ago · completed')
  for (const status of ['killed','stopped','cancelled']) expect(completedAgo({end:0,status},180000)).toBe(' · 3m ago · stopped')
  expect(completedAgo({end:0,status:'failed'},180000)).toBe(' · 3m ago · failed')
  expect(completedAgo({end:200000,status:'completed'},180000)).toBe(' · just now · completed')
})
test('waiting 舊檔、缺 percent、無效欄位與十分鐘邊界', () => {
  const old = parseContext('{"sessionId":"one","percent":41,"updatedAt":0}')!
  expect(isWaiting(old,0)).toBe(false)
  const waiting = parseContext('{"sessionId":"one","waiting":true,"updatedAt":0}')!
  expect(waiting).toEqual({sessionId:'one',waiting:true,updatedAt:0})
  expect(isWaiting(waiting,599999)).toBe(true)
  expect(isWaiting(waiting,600000)).toBe(true)
  expect(isWaiting(waiting,600001)).toBe(false)
  expect(isWaiting({...waiting,waiting:false},0)).toBe(false)
  for (const fields of ['"waiting":"true"','"waiting":null','"percent":null','"percent":101','"percent":1.5']) {
    expect(parseContext(`{"sessionId":"one","updatedAt":0,${fields}}`)).toBeNull()
  }
})
test('子代理只顯示四種未結束狀態，保留順序與資料', () => {
  const statuses: AgentInfo['status'][] = ['pending','running','waiting','idle','completed','failed','killed']
  const agents = statuses.map((status,i) => ({id:String(i),type:'Explore',description:'task',status}))
  expect(visibleAgents(agents)).toEqual(agents.slice(0,4))
  expect(visibleAgents([])).toEqual([])
  expect(visibleAgents(agents.slice(4))).toEqual([])
})
test('背景工作數量是執行中外部指令加顯示中的子代理', () => {
  const agents: AgentInfo[] = [{id:'one',type:'Explore',description:'task',status:'waiting'}]
  expect(backgroundCount([{end:null},{end:0}],agents)).toBe(2)
  expect(backgroundCount([],[])).toBe(0)
  expect(backgroundCount([{end:0}],agents.map(agent => ({...agent,status:'completed'})))).toBe(0)
  expect(backgroundCount([{end:null}],[])).toBe(1)
})
test('背景工作：跑的全顯示、完成的補空位、展開看全部', () => {
  const run = (id: string, end: number | null) => ({ id, agent: 'muse' as const, label: id, start: 0, end, status: end === null ? 'running' : 'completed' })
  const ids = (rows: { id: string }[]) => rows.map(r => r.id)
  const six = ['a','b','c','d','e','f'].map(id => run(id, null))
  expect(visibleRuns(six,false)).toEqual({ rows: six, hiddenDone: 0 })
  const sparse = [run('d1',1), run('d2',2), run('r1',null)]
  expect(visibleRuns(sparse,false)).toEqual({ rows: sparse, hiddenDone: 0 })
  const mixed = [run('d1',1), run('d2',2), run('d3',3), run('r1',null), run('r2',null)]
  expect(ids(visibleRuns(mixed,false).rows)).toEqual(['d2','d3','r1','r2'])
  expect(visibleRuns(mixed,false).hiddenDone).toBe(1)
  expect(ids(visibleRuns(mixed,true).rows)).toEqual(['d1','d2','d3','r1','r2'])
  expect(visibleRuns([...six, run('d1',1)],false)).toEqual({ rows: six, hiddenDone: 1 })
})

test('jobs 只接受非負整數，壞欄位不丟掉 context', () => {
  const row = {sessionId:'one',percent:41,waiting:true,updatedAt:0}
  for (const jobs of [0,1,42]) expect(parseContext(JSON.stringify({...row,jobs}))).toEqual({...row,jobs})
  for (const jobs of [-1,0.5,'1',null,true,{},[]]) expect(parseContext(JSON.stringify({...row,jobs}))).toEqual(row)
})

test('一般背景工作計入總數、全顯示並減少完成列空位', () => {
  const tasks = Array.from({length:5},(_,i) => ({id:`shell-${i}`,type:'shell',label:'整理',start:0}))
  const done = [{id:'done',agent:'codex' as const,label:'完成',start:0,end:1,status:'completed'}]
  expect(backgroundCount(done,[],tasks)).toBe(5)
  expect(visibleRuns(done,false,tasks).rows.map(r => r.id)).toEqual(tasks.map(task => task.id))
  expect(visibleRuns(done,false,tasks).hiddenDone).toBe(1)
  expect(visibleRuns(done,true,tasks).rows).toHaveLength(6)
  expect(visibleRuns(done,false,tasks.slice(0,1)).rows.map(r => r.id)).toEqual(['done','shell-0'])
})

test('context 取百分比與實際 token 較高警示，涵蓋 200K 與 1M 視窗', () => {
  for (const window of [200000,1000000]) {
    expect([0,49,50,79,80,100].map(percent => contextColor(percent, percent / 100 * window))).toEqual(window === 200000 ? [undefined,undefined,'yellow','yellow','red','red'] : [undefined,'red','red','red','red','red'])
  }
  expect(contextColor(25,250000)).toBe('yellow')
  expect(contextColor(45,450000)).toBe('red')
  expect([199999,200000,399999,400000].map(tokens => contextColor(10,tokens))).toEqual([undefined,'yellow','yellow','red'])
  expect(contextColor(80,0)).toBe('red')
  expect(contextColor(50,0)).toBe('yellow')
  expect([49,50,79,80].map(percent => contextColor(percent,undefined))).toEqual([undefined,'yellow','yellow','red'])
})
test('tokens 只接受非負整數，壞欄位與缺值保留舊資料', () => {
  const row = {sessionId:'one',percent:25,updatedAt:0}
  expect(parseContext(JSON.stringify(row))).toEqual(row)
  for (const tokens of [0,250000]) expect(parseContext(JSON.stringify({...row,tokens}))).toEqual({...row,tokens})
  for (const tokens of [-1,0.5,'250000',null,true,{},[]]) expect(parseContext(JSON.stringify({...row,tokens}))).toEqual(row)
})

test('mix 嚴格檢查全部欄位，標籤只在警示時出現', () => {
  const row = {sessionId:'one',transcript:'/tmp/one.jsonl',offset:10,size:12,images:3,toolTokens:120000,complete:true,updatedAt:0}
  expect(parseMix(JSON.stringify(row))).toEqual(row)
  for (const text of ['broken','null','[]','{}']) expect(parseMix(text)).toBeNull()
  for (const key of Object.keys(row)) {
    const missing: Record<string, unknown> = {...row}
    delete missing[key]
    expect(parseMix(JSON.stringify(missing))).toBeNull()
    expect(parseMix(JSON.stringify({...row,[key]:null}))).toBeNull()
  }
  for (const key of ['offset','size','images','toolTokens']) {
    for (const value of [-1,0.5,'1',true,{},[]]) expect(parseMix(JSON.stringify({...row,[key]:value}))).toBeNull()
  }
  for (const fields of [{sessionId:'../bad'},{sessionId:''},{transcript:''},{transcript:2},{offset:13},{complete:'yes'},{complete:1},{updatedAt:-1},{updatedAt:'0'}]) expect(parseMix(JSON.stringify({...row,...fields}))).toBeNull()
  expect(parseMix(JSON.stringify(row).replace('"updatedAt":0','"updatedAt":1e999'))).toBeNull()
  configure()
  expect(mixLabel({contextPercent:30,contextTokens:300000,images:3,toolTokens:120000})).toBe('Images3 Tools40%')
  expect(mixLabel({contextPercent:50,contextTokens:100000,images:0,toolTokens:200000})).toBe('Tools100%')
  expect(mixLabel({contextPercent:50,contextTokens:0,images:0,toolTokens:0})).toBe('Tools0%')
  expect(mixLabel({contextPercent:19,contextTokens:190000,images:3,toolTokens:120000})).toBe('')
  expect(mixLabel({contextPercent:50})).toBe('')
})
