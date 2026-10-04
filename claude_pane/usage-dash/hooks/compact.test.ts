import { expect, test } from 'claude-code/testing'
import { compactLines } from './compact'

test('精簡版範例與各段配色', () => {
  const lines = compactLines({ agents: {
    'claude-code': { available:true, five_hour:{used_percent:11}, seven_day:{used_percent:21} },
    codex: { available:true, five_hour:{used_percent:1}, seven_day:{used_percent:17} },
    antigravity: { available:true, groups:[
      { name:'GEMINI MODELS', five_hour:{used_percent:28}, seven_day:{used_percent:55} },
      { name:'CLAUDE AND GPT MODELS', five_hour:{used_percent:0}, seven_day:{used_percent:1} },
    ] },
    grok: { available:true, period:{used_percent:28} },
  } }, [
    { id:'one', pid:1, status:'busy', title:'', source:'', mtimeMs:0 },
    { id:'two', pid:2, status:'idle', title:'', source:'', mtimeMs:0 },
  ], 0, 10000, 0)
  expect(lines.map(line => line.map(part => part.text).join(''))).toEqual([
    '◆ Claude 5h 11% Week 21%   ◆ Codex 5h 1% Week 17%',
    '◆ agy Gemini 28%/55%  Claude/GPT 0%/1%   ◆ Grok 28%',
    'Sessions 1 busy / 2 · Background jobs 0 · ↻ 10s ago',
  ])
  expect(lines.flat().filter(part => part.text.startsWith('◆')).map(part => part.color)).toEqual(['#d97757','#10a37f','#4285f4','white'])
  expect(lines[1].filter(part => part.text.endsWith('%')).map(part => part.color)).toEqual(['green','yellow','green','green','green'])
  expect(lines[2][1]?.color).toBeUndefined()
})

test('全部 agent 沒資料、零對話與未更新仍保留三行', () => {
  const lines = compactLines({agents:{}}, [], 0, 0, null)
  expect(lines.map(line => line.map(part => part.text).join(''))).toEqual(['','','Sessions 0 busy / 0 · Background jobs 0 · ↻ —'])
})

test('agy 與 Grok 缺資料、不顯示 unavailable', () => {
  const lines = compactLines({agents:{
    'claude-code':{available:false,five_hour:{used_percent:100}},
    antigravity:{available:true,groups:[{name:'GEMINI MODELS'},{name:'Claude / GPT',seven_day:{used_percent:1}}]},
    grok:{available:true},
  }}, [], 0, 0, 0)
  expect(lines.map(line => line.map(part => part.text).join(''))).toEqual(['','◆ agy Claude/GPT 1%   ◆ Grok','Sessions 0 busy / 0 · Background jobs 0 · ↻ 0s ago'])
  expect(compactLines({agents:{antigravity:{available:true}}}, [], 0, 0, 0)[1]).toEqual([{text:'◆ agy',color:'#4285f4',bold:false}])
})

test('百分比 100 與執行中工作配色、更新時間不為負', () => {
  const lines = compactLines({agents:{grok:{available:true,period:{used_percent:100}}}}, [], 2, 0, 10000)
  expect(lines[1].find(part => part.text === '100%')?.color).toBe('red')
  expect(lines[2][1]).toEqual({text:'2',color:'yellow'})
  expect(lines[2].map(part => part.text).join('')).toBe('Sessions 0 busy / 0 · Background jobs 2 · ↻ 0s ago')
})
