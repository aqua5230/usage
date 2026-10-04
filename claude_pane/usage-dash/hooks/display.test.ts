import { expect, test } from 'claude-code/testing'
import { contextPercent, contextColor, parseContext, staleContext, completedAgo } from './display'
test('context 百分比單位、缺值與三種顏色門檻', () => {
  expect(contextPercent(undefined)).toBeUndefined()
  expect(contextPercent(0.41)).toBe(0)
  expect(contextPercent(0.9)).toBe(1)
  expect(contextPercent(41.6)).toBe(42)
  expect([0,69,70,84,85,100].map(contextColor)).toEqual([undefined,undefined,'yellow','yellow','red','red'])
  expect(parseContext('broken')).toBeNull()
  expect(parseContext('{"sessionId":"one","updatedAt":0}')).toBeNull()
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
