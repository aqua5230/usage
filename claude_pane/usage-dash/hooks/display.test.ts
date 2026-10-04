import type { AgentInfo } from 'claude-code'
import { expect, test } from 'claude-code/testing'
import { contextPercent, contextColor, parseContext, staleContext, completedAgo, isWaiting, visibleAgents, backgroundCount } from './display'
test('context 百分比單位、缺值與三種顏色門檻', () => {
  expect(contextPercent(undefined)).toBeUndefined()
  expect(contextPercent(0.41)).toBe(0)
  expect(contextPercent(0.9)).toBe(1)
  expect(contextPercent(41.6)).toBe(42)
  expect([0,69,70,84,85,100].map(contextColor)).toEqual([undefined,undefined,'yellow','yellow','red','red'])
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
