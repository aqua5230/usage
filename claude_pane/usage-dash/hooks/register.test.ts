import { expect, mock, test } from 'claude-code/testing'
import { parseQuota, resetTime } from './quota'
import type { PluginState } from 'claude-code'
type Drawn = { type?: string; props?: Record<string, unknown>; children?: unknown[] }
function flatText(node: unknown): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (!node || typeof node !== 'object') return ''
  return ((node as Drawn).children ?? []).map(flatText).join('')
}
function elements(node: unknown): Drawn[] {
  if (!node || typeof node !== 'object') return []
  const element = node as Drawn
  return [element, ...(element.children ?? []).flatMap(elements)]
}
for (const mode of ['full', 'missing', 'empty'] as const) {
  test(`inline 固定三行、無框線與按鈕：${mode}`, async ($, on) => {
    mock.clock(on, {now:10000})
    on('session.id', () => ({value:'one'}))
    const values: PluginState['usage-dash'] = { agents:[],
      quotas:{agents:mode === 'empty' ? {} : mode === 'missing' ? {antigravity:{available:true},grok:{available:true}} : {
        'claude-code':{available:true,five_hour:{used_percent:11},seven_day:{used_percent:21}},
        codex:{available:true,five_hour:{used_percent:1},seven_day:{used_percent:17}},
        antigravity:{available:true,groups:[{name:'GEMINI MODELS',five_hour:{used_percent:28},seven_day:{used_percent:55}},{name:'CLAUDE AND GPT MODELS',five_hour:{used_percent:0},seven_day:{used_percent:1}}]},
        grok:{available:true,period:{used_percent:28}},
      }},
      updated:0,quotaError:'不顯示Quota錯誤',sessionError:'不顯示對話錯誤',collapsed:{quota:true,sessions:true,runs:true},more:false,
      sessions:mode === 'full' ? [{id:'one',pid:1,status:'busy',title:'',source:'',mtimeMs:0},{id:'two',pid:2,status:'idle',title:'',source:'',mtimeMs:0}] : [],
      runs:mode === 'missing' ? [{id:'run',agent:'codex',label:'',start:0,end:null,status:'running'}] : [],
    }
    on('state.get', ($,e) => ({value:{value:values[e.key],version:0}}))
    const ui = await $.ui.mount({plugin:'usage-dash',surface:'terminal',component:'Pane',requestId:'usage-dash',props:{title:'Usage',isFocused:true,bodyColumns:80,placement:'inline',scroll:{offset:0,bodyRows:3},view:{}}})
    const tree = await ui.drawn() as Drawn
    const rows = tree.children as Drawn[]
    expect(rows).toHaveLength(3)
    expect(rows.map(row => row.type)).toEqual(['Text','Text','Text'])
    expect(rows.map(row => row.props?.wrap)).toEqual(['wrap','wrap','wrap'])
    expect(await ui.findAll({type:'Button'})).toHaveLength(0)
    expect(elements(tree).some(node => node.props?.borderStyle !== undefined)).toBe(false)
    const expected = mode === 'full' ? [
      '◆ Claude 5h 11% Week 21%   ◆ Codex 5h 1% Week 17%',
      '◆ agy Gemini 28%/55%  Claude/GPT 0%/1%   ◆ Grok 28%',
      'Sessions 1 busy / 2 · Background jobs 0 · ↻ 10s ago',
    ] : [' ',mode === 'missing' ? '◆ agy   ◆ Grok' : ' ',`Sessions 0 busy / 0 · Background jobs ${mode === 'missing' ? 1 : 0} · ↻ 10s ago`]
    expect(rows.map(flatText)).toEqual(expected)
    const parts = elements(tree).filter(node => node.type === 'Text' && node.props?.wrap === undefined)
    expect(parts.every(part => part.props?.dimColor === !part.props?.color)).toBe(true)
    expect(parts.find(part => flatText(part) === (mode === 'missing' ? '1' : '0'))?.props?.color).toBe(mode === 'missing' ? 'yellow' : undefined)
  })
}
test('四家額度、三個對話、一筆工作與收合按鈕', async ($, on) => {
  mock.clock(on, { now: 1000000 })
  on('session.id', () => ({value:'s1'}))
  const fixture = JSON.stringify({ agents: {
    'claude-code': { available:true, model:'Opus 5.5', five_hour:{used_percent:58,resets_in_seconds:2432},seven_day:{used_percent:15,resets_in_seconds:432000} },
    codex:{available:true,model:'gpt-6.1-sol',age_seconds:540,five_hour:{used_percent:82,resets_in_seconds:3540},seven_day:{used_percent:31,resets_in_seconds:259200}},
    antigravity:{available:true,age_seconds:120,groups:[{name:'GEMINI MODELS',five_hour:{used_percent:23.7,resets_in_seconds:5100},seven_day:{used_percent:53.9,resets_in_seconds:222300}},{name:'Claude / GPT',five_hour:{used_percent:12,resets_in_seconds:1200},seven_day:{used_percent:40,resets_in_seconds:86400}}]},
    grok:{available:true,tier:'XPremium',age_seconds:60,period:{used_percent:28,resets_in_seconds:176000}}
  }})
  const values: PluginState['usage-dash'] = { agents:[], quotas:parseQuota(fixture),updated:1000000,quotaError:'',sessionError:'',collapsed:{quota:false,sessions:false,runs:false},more:false,sessions:[
    {id:'s1',pid:1,status:'busy',mtimeMs:990000,title:'Usage面板',source:'usage',contextPercent:41},
    {id:'s2',pid:2,status:'busy',mtimeMs:950000,title:'整理筆記',source:'notes · Desktop',contextPercent:70},
    {id:'s3',pid:3,status:'idle',mtimeMs:990000,title:'修測試',source:'tests',contextPercent:85}
  ],runs:[{id:'r1',agent:'codex',label:'檢查測試結果',start:808000,end:null,status:'running'},{id:'done',agent:'agy',label:'整理完成',start:700000,end:820000,status:'completed'},{id:'failed',agent:'grok',label:'檢查失敗',start:940000,end:970000,status:'failed'}] }
  on('state.get', ($, e) => ({ value: { value: values[e.key], version: 0 } }))
  on('state.set', ($, e) => { Object.assign(values, { [e.key]: e.value }); return {value:{isSet:true,version:1}} })
  const ui = await $.ui.mount({plugin:'usage-dash',surface:'terminal',component:'Pane',requestId:'usage-dash',props:{title:'Usage',isFocused:true,bodyColumns:60,placement:'dock',scroll:{offset:0,bodyRows:40},view:{}}})
  const rows = await ui.findAll({type:'Text'})
  const buttons = await ui.findAll({type:'Button'})
  expect(buttons).toHaveLength(3)
  expect(rows.some(row => row.text.includes('(here)Usage面板'))).toBe(true)
  expect(rows.some(row => row.text === '2 busy / 3')).toBe(true)
  const tree = await ui.drawn()
  const lines: string[] = []
  function walk(node: unknown) {
    if (!node || typeof node !== 'object') return
    const element = node as {type?:string;props?:{label?:string;plain?:boolean};children?:unknown[]}
    if (element.type === 'Text') {
      lines.push(flatText(element))
    } else if (element.type === 'Button') {
      lines.push(element.props?.plain ? element.props.label ?? '' : `[ ${element.props?.label ?? ''} ]`)
    } else { for (const child of element.children ?? []) walk(child) }
  }
  walk(tree)
  const statusRows = elements(tree).filter(n => n.props?.justifyContent === 'space-between' && /Busy|Idle/.test(flatText(n)))
  expect(statusRows).toHaveLength(3)
  for (const row of statusRows) {
    expect(row.children).toHaveLength(1)
    expect(flatText(row)).not.toContain('%')
  }
  await ui.press({key:'quota'})
  await ui.redraw()
  expect(await ui.find({type:'Text',text:/▎ Claude/})).toBeUndefined()
  await ui.press({key:'quota'})
  await ui.redraw()
  expect(await ui.find({type:'Text',text:/▎ Claude/})).toBeDefined()
  await ui.press({key:'sessions'})
  await ui.redraw()
  expect(await ui.find({type:'Text',text:/Usage面板/})).toBeUndefined()
  await ui.press({key:'runs'})
  await ui.redraw()
  expect(await ui.find({type:'Text',text:/檢查測試結果/})).toBeUndefined()
  expect(values.collapsed).toEqual({quota:false,sessions:true,runs:true})
  values.collapsed = {...values.collapsed,sessions:false}
  values.sessions = [...values.sessions,...Array.from({length:3},(_,i) => ({id:`extra-${i}`,title:`其他對話 ${i}`,source:'Terminal',pid:i+10,status:'idle',mtimeMs:0}))]
  await ui.redraw()
  expect(await ui.find({type:'Text',text:/其他對話 2/})).toBeUndefined()
  await ui.press({key:'more'}); await ui.redraw()
  expect(await ui.find({type:'Text',text:/其他對話 2/})).toBeDefined()
  await ui.press({key:'more'}); await ui.redraw()
  expect(await ui.find({type:'Text',text:/其他對話 2/})).toBeUndefined()
  expect(lines.join('\n')+'\n').toBe(`[ ▾ Quota ]
▎ Claude
Opus 5.5
  5h    ■■■■■■□□□□  58%  ${resetTime({used_percent:58,resets_in_seconds:2432},1000000)}
  Week  ■■□□□□□□□□  15%  ${resetTime({used_percent:15,resets_in_seconds:432000},1000000)}
▎ Codex
gpt-6.1-sol
  5h    ■■■■■■■■□□  82%  ${resetTime({used_percent:82,resets_in_seconds:3540},1000000)}
  Week  ■■■□□□□□□□  31%  ${resetTime({used_percent:31,resets_in_seconds:259200},1000000)}
▎ agy
  Gemini
  5h    ■■□□□□□□□□  24%  ${resetTime({used_percent:24,resets_in_seconds:5100},1000000)}
  Week  ■■■■■□□□□□  54%  ${resetTime({used_percent:54,resets_in_seconds:222300},1000000)}
  Claude / GPT
  5h    ■□□□□□□□□□  12%  ${resetTime({used_percent:12,resets_in_seconds:1200},1000000)}
  Week  ■■■■□□□□□□  40%  ${resetTime({used_percent:40,resets_in_seconds:86400},1000000)}
▎ Grok XPremium
  Period ■■■□□□□□□□  28%  ${resetTime({used_percent:28,resets_in_seconds:176000},1000000)}
[ ▾ Claude sessions ]
2 busy / 3
● usage (here)Usage面板
41%
    Busy
● notes · Desktop 整理筆記
70%
    Busy
● tests 修測試
85%
    Idle just now
[ ▾ Background jobs ]
1
3m12s  codex  檢查測試結果
✓ 2m00s  agy  整理完成 · 3m ago · completed
✗ 0m30s  grok  檢查失敗 · just now · failed
↻ 0s ago
`)

})

test('啟動、CLI 備援、存活對話清單與定時更新', async ($, on) => {
  const clock = mock.clock(on,{now:1000000})
  mock.env(on,{HOME:'/假家目錄'})
  const values: Record<string,unknown> = {}
  const commands: string[][] = []
  let agentCalls = 0
  on('agent.list', () => {
    if (++agentCalls > 1) throw new Error('agent list unavailable')
    return {value:[{id:'child',type:'Explore',description:'讀程式',status:'running'},{id:'done',type:'Explore',description:'已結束',status:'completed'}]}
  })
  on('state.get', ($,e) => ({value:{value:values[e.key],version:0}}))
  on('state.set', ($,e) => {values[e.key]=e.value;return {value:{isSet:true,version:1}}})
  on('ui.open', () => ({value:{isPlaced:true}}))
  on('ui.invalidate', () => ({value:undefined}))
  on('command.register', ($,e) => ({value:{command:e.name}}))
  on('session.start', ($,e) => ({cwd:e.cwd}))
    on('session.usage', () => { throw new Error('no context yet') })
    on('fs.write', () => ({value:undefined}))
    on('fs.exists', () => ({value:false}))
  const readFiles: string[] = []
  on('fs.list', ($,e) => {
    if (e.path === '/假家目錄/.usage/claude-pane/live') return {value:[]}
    expect(e.path).toBe('/假家目錄/.claude/sessions')
    return {value:['1.json','2.json','3.json','4.json','5.json','1.hash.key'].map(name => ({name,kind:'file' as const,size:10,mtimeMs:990000,isLink:false}))}
  })
  on('fs.read', ($,e) => {
    readFiles.push(e.path)
    const pid = Number(e.path.split('/').pop()!.split('.')[0])
    return {value:pid === 4 ? 'broken' : JSON.stringify({pid,sessionId:pid === 1 ? 'one' : `s${pid}`,name:`名稱${pid}`,cwd:'/Users/x/usage/',entrypoint:pid === 3 ? 'claude-desktop' : 'cli',kind:pid === 5 ? 'background' : 'interactive',status:pid === 3 ? 'busy' : 'idle',updatedAt:990000,statusUpdatedAt:pid === 5 ? 995000 : 990000})}
  })
  on('process.run', ($,e) => {
    commands.push([...e.argv])
    const success = e.argv[0] !== 'usage'
    const stdout = e.argv[0] === 'ps' ? ' 1\n 3\n 5\n' : e.argv[0] === '/bin/sh' ? (e.argv[5] === 'one' ? '/假家目錄/.claude/projects/project/one.jsonl\n' : e.argv[5] === 's5' ? '/假家目錄/.claude/projects/project/s5.jsonl\n' : '') : e.argv[0] === 'tail' ? (e.argv[3]?.endsWith('one.jsonl') ? '{"type":"ai-title","aiTitle":"假對話","entrypoint":"other"}' : '') : '{"agents":{"codex":{"available":true,"model":"假模型"}}}'
    return {value:{exitCode:success ? 0 : 127,stdout:success ? stdout : '',stderr:success ? '' : 'not found',isStdoutTruncated:false,isStderrTruncated:false}}
  })
  await $.session.start({cwd:'/假專案',surface:'terminal',isInteractive:true})
  expect(values.agents).toEqual([{id:'child',type:'Explore',description:'讀程式',status:'running'}])
  expect(commands.filter(argv => argv[0] === 'ps')).toEqual([['ps','-o','pid=','-p','1,2,3,5']])
  expect(commands.filter(argv => argv[0] === '/bin/sh')).toEqual(['one','s3','s5'].map(id => ['/bin/sh','-c','ls "$1"/*/"$2".jsonl 2>/dev/null | head -1','sh','/假家目錄/.claude/projects',id]))
  expect(readFiles.filter(path => path.startsWith('/假家目錄/.claude/sessions/'))).toHaveLength(5)
  expect(readFiles.some(path => path.endsWith('.key'))).toBe(false)
  expect(values.sessions).toEqual([
    {id:'s3',pid:3,title:'名稱3',source:'usage · Desktop',mtimeMs:990000,status:'busy'},
    {id:'s5',pid:5,title:'名稱5',source:'usage',mtimeMs:995000,status:'idle'},
    {id:'one',pid:1,title:'假對話',source:'usage',mtimeMs:990000,status:'idle'}
  ])
  await clock.advance(15000)
  expect(agentCalls).toBe(2)
  expect(values.agents).toEqual([])
  expect(commands.filter(argv => argv[0] === 'tail')).toHaveLength(4)
  expect(commands.filter(argv => argv[0] === 'usage')).toHaveLength(1)
  await clock.advance(45000)
  expect(commands.filter(argv => argv[0] === 'usage')).toHaveLength(2)
  expect(values.updated).toBe(1060000)
})

for (const mode of ['empty', 'ps-exit-1', 'ps-reject'] as const) {
  test(`無存活對話：${mode}`, async ($, on) => {
    mock.clock(on,{now:1000000})
    mock.env(on,{HOME:'/假家目錄'})
    const values: Record<string,unknown> = {}
    const commands: string[][] = []
    on('state.get', ($,e) => ({value:{value:values[e.key],version:0}}))
    on('state.set', ($,e) => {values[e.key]=e.value;return {value:{isSet:true,version:1}}})
    on('ui.open', () => ({value:{isPlaced:true}}))
    on('command.register', ($,e) => ({value:{command:e.name}}))
    on('session.start', ($,e) => ({cwd:e.cwd}))
    on('session.usage', () => { throw new Error('no context yet') })
    on('fs.write', () => ({value:undefined}))
    on('fs.exists', () => ({value:false}))
    on('fs.list', () => ({value:mode === 'empty' ? [] : [{name:'1.json',kind:'file',size:10,mtimeMs:0,isLink:false}]}))
    on('fs.read', () => ({value:'{"pid":1,"sessionId":"dead","updatedAt":0}'}))
    on('process.run', ($,e) => {
      commands.push([...e.argv])
      if (e.argv[0] === 'ps' && mode === 'ps-reject') throw new Error('ps unavailable')
      return {value:{exitCode:e.argv[0] === 'ps' ? 1 : 0,stdout:e.argv[0] === 'ps' ? '1' : '{"agents":{}}',stderr:'',isStdoutTruncated:false,isStderrTruncated:false}}
    })
    await $.session.start({cwd:'/假專案',surface:'terminal',isInteractive:true})
    expect(values.sessions).toEqual([])
    expect(values.sessionError).toBe('')
    expect(commands.filter(argv => argv[0] === 'ps')).toHaveLength(mode === 'empty' ? 0 : 1)
    expect(commands.some(argv => argv[0] === '/bin/sh' || argv[0] === 'tail')).toBe(false)
  })
}

for (const bodyColumns of [10, 43, 44, 200]) {
  test(`分段顏色、忙閒圓點與面板寬度 ${bodyColumns}`, async ($, on) => {
    mock.clock(on, { now: 1000000 })
    on('session.id', () => ({value:'busy'}))
    const values: PluginState['usage-dash'] = { agents:[],
      quotas:{agents:{codex:{available:true,five_hour:{used_percent:82,resets_in_seconds:3600}}}},
      updated:1000000,quotaError:'',sessionError:'',collapsed:{quota:false,sessions:false,runs:false},more:false,runs:[],
      sessions:[{id:'busy',pid:1,status:'busy',title:'忙對話',source:'Terminal',mtimeMs:999000},{id:'idle',pid:2,status:'idle',title:'閒對話',source:'Desktop',mtimeMs:800000}]
    }
    on('state.get', ($, e) => ({value:{value:values[e.key],version:0}}))
    const ui = await $.ui.mount({plugin:'usage-dash',surface:'terminal',component:'Pane',requestId:'usage-dash',props:{title:'Usage',isFocused:true,bodyColumns,placement:'dock',scroll:{offset:0,bodyRows:40},view:{}}})
    const nodes = elements(await ui.drawn())
    const quota = nodes.find(n => n.type === 'Text' && n.children?.some(c => flatText(c) === '  5h    '))!
    expect(quota.props?.color).toBeUndefined()
    const parts = (quota.children ?? []).filter(c => typeof c === 'object') as Drawn[]
    expect(parts.map(n => n.props?.color)).toEqual([undefined,'#d70000',undefined,'#d70000',undefined])
    expect(parts.map(n => n.props?.dimColor === true)).toEqual([true,false,true,false,true])
    expect(flatText(parts[1]).length + flatText(parts[2]).length).toBe(bodyColumns < 44 ? 8 : 10)
    expect(flatText(parts[1])).toBe('■'.repeat(bodyColumns < 44 ? 7 : 8))
    expect(flatText(parts[2])).toBe('□'.repeat(bodyColumns < 44 ? 1 : 2))
    const dots = nodes.filter(n => n.type === 'Text' && flatText(n) === '●')
    expect(dots.map(n => n.props?.color)).toEqual(['green',undefined])
    expect(dots.map(n => n.props?.dimColor)).toEqual([false,true])
  })
}

test('context 靠右、顏色門檻、無資料隱藏與底部只留更新時間', async ($, on) => {
  mock.clock(on,{now:60000})
  on('session.id', () => ({value:'one'}))
  const values: PluginState['usage-dash'] = { agents:[],
    quotas:{agents:{}},updated:59000,quotaError:'',sessionError:'',collapsed:{quota:true,sessions:false,runs:true},more:true,runs:[],
    sessions:[undefined,0,69,70,84,85,100].map((percent,i) => ({id:String(i),pid:i+1,title:`對話${i}`,source:'usage',mtimeMs:59000,status:'idle',...(percent === undefined ? {} : {contextPercent:percent})}))
  }
  on('state.get', ($,e) => ({value:{value:values[e.key],version:0}}))
  const ui = await $.ui.mount({plugin:'usage-dash',surface:'terminal',component:'Pane',requestId:'usage-dash',props:{title:'Usage',isFocused:true,bodyColumns:60,placement:'dock',scroll:{offset:0,bodyRows:40},view:{}}})
  const nodes = elements(await ui.drawn())
  const percents = nodes.filter(n => n.type === 'Text' && /^\d+%$/.test(flatText(n)))
  expect(percents.map(flatText)).toEqual(['0%','69%','70%','84%','85%','100%'])
  expect(percents.map(n => n.props?.color)).toEqual([undefined,undefined,'yellow','yellow','red','red'])
  expect(percents.map(n => n.props?.dimColor === true)).toEqual([true,true,false,false,false,false])
  for (const percent of percents) {
    const parent = nodes.find(n => n.children?.includes(percent))!
    expect(flatText(parent)).toMatch(/^\d+%$/)
    expect(parent.props?.flexShrink).toBe(0)
    expect(parent.props?.marginLeft).toBe(1)
    const row = nodes.find(n => n.children?.includes(parent))!
    expect(row.props?.justifyContent).toBe('space-between')
    expect(row.children?.[row.children.length-1]).toBe(parent)
    expect(flatText(row)).toContain('對話')
    expect(flatText(row)).not.toContain('Idle')
    expect(flatText(row)).not.toMatch(/[■□━─]/)
  }
  const sessionRows = nodes.filter(n => n.props?.justifyContent === 'space-between' && flatText(n).includes('對話'))
  expect(sessionRows).toHaveLength(7)
  expect(flatText(sessionRows[0])).not.toContain('%')
  const statusRows = nodes.filter(n => n.props?.justifyContent === 'space-between' && flatText(n).includes('Idle'))
  expect(statusRows).toHaveLength(7)
  for (const row of statusRows) {
    expect(row.children).toHaveLength(1)
    expect(flatText(row)).not.toContain('%')
    expect(flatText(row)).not.toMatch(/[■□━─]/)
  }
  const footer = nodes.find(n => n.props?.justifyContent === 'flex-end')!
  expect(flatText(footer)).toBe('↻ 1s ago')
  expect(footer.children).toHaveLength(1)
  expect(flatText(await ui.drawn()).includes('點標題收合')).toBe(false)
})
for (const writeFails of [false,true]) {
  test(`自己回報、回合更新與 live 清掃：寫入失敗 ${writeFails}`, async ($, on) => {
    const now = 172800000, directory = '/假家目錄/.usage/claude-pane/live'
    const clock = mock.clock(on,{now})
    mock.env(on,{HOME:'/假家目錄'})
    const values: Record<string,unknown> = {}, written: string[] = [], commands: string[][] = []
    const files: Record<string,{text:string;mtimeMs:number}> = {
      one:{text:JSON.stringify({sessionId:'one',percent:41,updatedAt:0}),mtimeMs:0},
      old:{text:JSON.stringify({sessionId:'old',percent:50,updatedAt:0}),mtimeMs:0},
      unrelated:{text:'{"keep":"unrelated"}',mtimeMs:0},
      mismatch:{text:JSON.stringify({sessionId:'different',percent:50,updatedAt:0}),mtimeMs:0},
      empty:{text:'{}',mtimeMs:0},
      numeric:{text:JSON.stringify({sessionId:123,percent:50,updatedAt:0}),mtimeMs:0},
      Case:{text:JSON.stringify({sessionId:'case',percent:50,updatedAt:0}),mtimeMs:0},
      boundary:{text:JSON.stringify({sessionId:'boundary',percent:50,updatedAt:now-86400000}),mtimeMs:now-86400000},
      recent:{text:JSON.stringify({sessionId:'recent',percent:50,updatedAt:now-1000}),mtimeMs:now-1000},
      newMtime:{text:JSON.stringify({sessionId:'newMtime',percent:50,updatedAt:0}),mtimeMs:now-1000},
      newReport:{text:JSON.stringify({sessionId:'newReport',percent:50,updatedAt:now-1000}),mtimeMs:0},
    }
    on('session.id', () => ({value:'one'}))
    on('session.usage', () => ({value:{startedAt:0,context:{window:200000,percent:41.4},rateLimits:[]}}))
    on('state.get', ($,e) => ({value:{value:values[e.key],version:0}}))
    on('state.set', ($,e) => {values[e.key]=e.value;return {value:{isSet:true,version:1}}})
    on('command.register', ($,e) => ({value:{command:e.name}}))
    on('ui.open', () => ({value:{isPlaced:true}}))
    on('ui.invalidate', () => ({value:undefined}))
    on('session.start', ($,e) => ({cwd:e.cwd}))
    on('turn.complete', ($,e) => ({text:e.answer}))
    on('fs.exists', () => ({value:false}))
    on('fs.write', ($,e) => {
      expect(e.path).toBe(`${directory}/one.json`)
      written.push(e.text)
      if (writeFails) throw new Error('write denied')
      files.one = {text:e.text,mtimeMs:JSON.parse(e.text).updatedAt}
      return {value:undefined}
    })
    on('fs.list', ($,e) => ({value:e.path === directory ? Object.entries(files).map(([id,file]) => ({name:`${id}.json`,kind:'file' as const,size:10,mtimeMs:file.mtimeMs,isLink:false})) : [{name:'1.json',kind:'file',size:10,mtimeMs:0,isLink:false}]}))
    on('fs.read', ($,e) => ({value:e.path.startsWith(directory) ? files[e.path.split('/').pop()!.slice(0,-5)]!.text : JSON.stringify({pid:1,sessionId:'one',cwd:'/Users/x/usage',entrypoint:'cli',status:'idle',updatedAt:now})}))
    on('process.run', ($,e) => {
      commands.push([...e.argv])
      if (e.argv[0] === 'rm') delete files[e.argv[2]!.split('/').pop()!.slice(0,-5)]
      return {value:{exitCode:0,stdout:e.argv[0] === 'ps' ? '1' : e.argv[0] === 'usage' ? '{"agents":{}}' : '',stderr:'',isStdoutTruncated:false,isStderrTruncated:false}}
    })
    await $.session.start({cwd:'/假專案',surface:'terminal',isInteractive:true})
    expect(JSON.parse(written[0]!)).toEqual({sessionId:'one',percent:41,waiting:false,updatedAt:now})
    expect(commands.filter(argv => argv[0] === 'mkdir')).toEqual([])
    expect(commands.filter(argv => argv[0] === 'rm')).toEqual([['rm','-f',`${directory}/old.json`]])
    expect(values.sessions).toEqual([{id:'one',pid:1,title:'',source:'usage',mtimeMs:now,status:'idle',contextPercent:41,...(writeFails ? {} : {waiting:false,waitingUpdatedAt:now})}])
    expect(values.sessionError).toBe('')
    await clock.advance(1000)
    const result = await $.turn.complete({answer:'完成',durationMs:1000,isAborted:false,turnId:'turn',reason:'answer'})
    expect(result).toEqual({text:'完成'})
    expect(JSON.parse(written[1]!)).toEqual({sessionId:'one',percent:41,waiting:false,updatedAt:now+1000})
    await clock.advance(14000)
    expect(commands.filter(argv => argv[0] === 'rm')).toEqual(['old','boundary'].map(id => ['rm','-f',`${directory}/${id}.json`]))
    for (const id of ['unrelated','mismatch','empty','numeric','Case']) expect(files[id]).toBeDefined()
  })
}

for (const writeFails of [false,true]) {
  test(`Windows live 清掃與對話紀錄：寫入失敗 ${writeFails}`, async ($, on) => {
    const now = 172800000, commands: string[][] = [], lists: string[] = [], reads: string[] = [], stats: string[] = [], values: Record<string,unknown> = {}
    const normalize = (path: string) => path.replaceAll('\\','/').replace(/^[A-Za-z]:/, '')
    mock.clock(on,{now})
    mock.env(on,{HOME:'/假家目錄',OS:'Windows_NT'})
    on('session.id', () => ({value:'one'}))
    on('session.usage', () => ({value:{startedAt:0,context:{window:200000,percent:41.4},rateLimits:[]}}))
    on('state.get', ($,e) => ({value:{value:values[e.key],version:0}}))
    on('state.set', ($,e) => {values[e.key]=e.value;return {value:{isSet:true,version:1}}})
    on('command.register', ($,e) => ({value:{command:e.name}}))
    on('ui.open', () => ({value:{isPlaced:true}}))
    on('session.start', ($,e) => ({cwd:e.cwd}))
    on('fs.write', () => {
      if (writeFails) throw new Error('write denied')
      return {value:undefined}
    })
    on('fs.list', ($,e) => {
      const path = normalize(e.path); lists.push(path)
      if (path.endsWith('/.claude/sessions')) return {value:[
        {name:'one.json',kind:'file' as const,size:10,mtimeMs:0,isLink:false},
        {name:'large.json',kind:'file' as const,size:10,mtimeMs:0,isLink:false},
        {name:'dead.json',kind:'file' as const,size:10,mtimeMs:0,isLink:false},
      ]}
      if (path.endsWith('/.claude/projects')) return {value:[
        {name:'project-one',kind:'dir' as const,size:0,mtimeMs:0,isLink:false},
        {name:'project-large',kind:'dir' as const,size:0,mtimeMs:0,isLink:false},
      ]}
      if (path.endsWith('/.usage/claude-pane/live')) return {value:[{name:'old.json',kind:'file' as const,size:10,mtimeMs:0,isLink:false}]}
      return {value:[]}
    })
    on('fs.exists', ($,e) => ({value:normalize(e.path).endsWith('/project-one/one.jsonl') || normalize(e.path).endsWith('/project-large/large.jsonl')}))
    on('fs.stat', ($,e) => {
      const path = normalize(e.path); stats.push(path)
      return {value:{size:path.endsWith('/large.jsonl') ? 4 * 1024 * 1024 + 1 : 10}}
    })
    on('fs.read', ($,e) => {
      const path = normalize(e.path); reads.push(path)
      if (path.endsWith('/.claude/sessions/one.json')) return {value:JSON.stringify({pid:1,sessionId:'one',cwd:'/專案',entrypoint:'cli',status:'idle',updatedAt:now})}
      if (path.endsWith('/.claude/sessions/large.json')) return {value:JSON.stringify({pid:2,sessionId:'large',cwd:'/大檔',entrypoint:'cli',status:'idle',updatedAt:now})}
      if (path.endsWith('/.claude/sessions/dead.json')) return {value:JSON.stringify({pid:3,sessionId:'dead',cwd:'/死檔',entrypoint:'cli',status:'idle',updatedAt:now})}
      if (path.endsWith('/project-one/one.jsonl')) return {value:'{"type":"ai-title","aiTitle":"Windows 標題","entrypoint":"cli"}'}
      if (path.endsWith('/.usage/claude-pane/live/one.json')) throw new Error('ENOENT')
      if (path.endsWith('/.usage/claude-pane/live/old.json')) return {value:JSON.stringify({sessionId:'old',percent:50,updatedAt:0})}
      throw new Error(`unexpected read: ${path}`)
    })
    on('process.run', ($,e) => {
      commands.push([...e.argv])
      return {value:{exitCode:0,stdout:e.argv[0] === 'tasklist' ? '"claude.exe","1","Console"\r\n"claude.exe","2","Console"' : e.argv[0] === 'usage' ? '{"agents":{}}' : '',stderr:'',isStdoutTruncated:false,isStderrTruncated:false}}
    })
    await $.session.start({cwd:'/假專案',surface:'terminal',isInteractive:true})
    expect(commands.filter(argv => argv[0] === 'tasklist')).toEqual([['tasklist','/FO','CSV','/NH']])
    expect((values.sessions as {id:string;title:string}[]).map(({id,title}) => ({id,title}))).toEqual([{id:'one',title:'Windows 標題'},{id:'large',title:''}])
    const deletes = commands.filter(argv => argv[0] === 'cmd')
    expect(deletes).toHaveLength(1)
    expect(deletes[0]!.slice(0,-1)).toEqual(['cmd','/d','/c','del','/f','/q'])
    expect(deletes[0]![6]).toMatch(/^[^/]*\\old\.json$/)
    expect(commands.some(argv => ['rm','ps','/bin/sh','tail','mkdir'].includes(argv[0]!))).toBe(false)
    expect(lists).toContain('/假家目錄/.claude/projects')
    expect(reads).toContain('/假家目錄/.claude/projects/project-one/one.jsonl')
    expect(stats).toContain('/假家目錄/.claude/projects/project-large/large.jsonl')
    expect(reads.some(path => path.endsWith('/large.jsonl'))).toBe(false)
    expect(values.sessionError).toBe('')
  })
}

for (const mode of ['installed', 'absent', 'invalid', 'unreadable'] as const) {
  test(`sidecar language, argv and fallback: ${mode}`, async ($, on) => {
    mock.clock(on, { now: 0 })
    mock.env(on, { HOME: '/test-home' })
    const commands: string[][] = [], descriptions: string[] = [], titles: string[] = [], logs: string[] = []
    const reads: string[] = [], values: Record<string, unknown> = {}
    const argv = ['/app path/python', '-c', 'bootstrap with spaces']
    on('state.get', ($, e) => ({ value: { value: values[e.key], version: 0 } }))
    on('state.set', ($, e) => { values[e.key] = e.value; return { value: { isSet: true, version: 1 } } })
    on('session.start', ($, e) => ({ cwd: e.cwd }))
    on('session.usage', () => { throw new Error('no context') })
    on('fs.list', () => ({ value: [] }))
    on('fs.exists', ($, e) => ({ value: e.path.endsWith('/usage-pane.json') && mode !== 'absent' }))
    on('fs.read', ($, e) => {
      reads.push(e.path)
      if (mode === 'unreadable') throw new Error('read denied')
      return { value: JSON.stringify(mode === 'invalid' ? { strings: {}, status_argv: [] } : {
        strings: { claude_pane_title: '使用狀態', claude_pane_description: '開啟面板', claude_pane_opened: '已開啟面板。' }, status_argv: argv
      }) }
    })
    on('ui.log', ($, e) => { logs.push(e.text); return { value: undefined } })
    on('ui.open', ($, e) => { titles.push(e.title ?? ''); return { value: { isPlaced: true } } })
    on('command.register', ($, e) => { descriptions.push(e.description); return { value: { command: e.name } } })
    on('process.run', ($, e) => {
      commands.push([...e.argv])
      const fail = mode !== 'installed' && e.argv[0] === 'usage'
      return { value: { exitCode: fail ? 127 : 0, stdout: fail ? '' : '{"agents":{}}', stderr: fail ? 'missing' : '', isStdoutTruncated: false, isStderrTruncated: false } }
    })
    await $.session.start({ cwd: '/project', surface: 'terminal', isInteractive: true })
    expect(reads.every(path => path.endsWith('/usage-dash/usage-pane.json'))).toBe(true)
    expect(reads).toHaveLength(mode === 'absent' ? 0 : 1)
    expect(commands).toEqual(mode === 'installed' ? [argv] : [['usage', 'status', '--json'], ['/test-home/.local/bin/usage', 'status', '--json']])
    expect(titles[0]).toBe(mode === 'installed' ? '使用狀態' : 'Usage')
    expect(descriptions[0]).toBe(mode === 'installed' ? '開啟面板' : 'Open the quota, Claude sessions and background jobs pane')
    expect(logs).toHaveLength(mode === 'invalid' || mode === 'unreadable' ? 1 : 0)
    const result = await $.command.run({ command: 'usage-dash', args: '', origin: {kind:'composer'}, presentation: {isFullscreen:true,columns:80} })
    expect(result.text).toBe(mode === 'installed' ? '已開啟面板。' : 'Usage pane opened.')
  })
}

for (const age of [599,601,3660]) {
  test(`寬版直條、灰字分組與黃色舊資料 ${age}`, async ($, on) => {
    mock.clock(on,{now:1000000})
    on('session.id', () => ({value:'one'}))
    const values: PluginState['usage-dash'] = { agents:[],
      quotas:{agents:{antigravity:{available:true,age_seconds:age,groups:[{name:'GEMINI MODELS'},{name:'CLAUDE AND GPT MODELS'}]}}},
      updated:1000000,quotaError:'',sessionError:'',collapsed:{quota:false,sessions:true,runs:true},more:false,runs:[],sessions:[]
    }
    on('state.get', ($,e) => ({value:{value:values[e.key],version:0}}))
    const ui = await $.ui.mount({plugin:'usage-dash',surface:'terminal',component:'Pane',requestId:'usage-dash',props:{title:'Usage',isFocused:true,bodyColumns:60,placement:'dock',scroll:{offset:0,bodyRows:40},view:{}}})
    const nodes = elements(await ui.drawn())
    expect(nodes.find(n => n.type === 'Text' && n.props?.color === '#4285f4' && flatText(n) === '▎ agy')?.props?.color).toBe('#4285f4')
    for (const title of ['  Gemini','  Claude / GPT']) expect(nodes.find(n => n.type === 'Text' && flatText(n) === title)?.props?.dimColor).toBe(true)
    const old = nodes.filter(n => n.type === 'Text' && n.props?.color === 'yellow')
    expect(old.map(flatText)).toEqual(age === 599 ? [] : [age === 601 ? ' · 10m ago' : ' · 1h ago'])
  })
}

test('另一個對話等你、子代理顏色順序與背景工作總數', async ($, on) => {
  mock.clock(on,{now:600000})
  on('session.id', () => ({value:'B'}))
  const values: PluginState['usage-dash'] = {
    quotas:{agents:{}},updated:600000,quotaError:'',sessionError:'',collapsed:{quota:true,sessions:false,runs:false},more:false,
    sessions:[{id:'A',pid:1,status:'busy',title:'另一個對話',source:'usage',mtimeMs:0,waiting:true,waitingUpdatedAt:0}],
    runs:[{id:'external',agent:'codex',label:'外部工作',start:590000,end:null,status:'running'}],
    agents:['running','waiting','idle','pending','completed','failed','killed'].map((status,i) => ({id:String(i),type:'Explore',description:`子代理${i}`,status:status as PluginState['usage-dash']['agents'][number]['status']}))
  }
  on('state.get', ($,e) => ({value:{value:values[e.key],version:0}}))
  const ui = await $.ui.mount({plugin:'usage-dash',surface:'terminal',component:'Pane',requestId:'usage-dash',props:{title:'Usage',isFocused:true,bodyColumns:60,placement:'dock',scroll:{offset:0,bodyRows:40},view:{}}})
  const nodes = elements(await ui.drawn())
  expect(nodes.some(n => flatText(n) === '1 busy / 1')).toBe(true)
  expect(nodes.some(n => flatText(n) === '5')).toBe(true)
  const waiting = nodes.filter(n => n.type === 'Text' && flatText(n) === 'waiting for you')
  expect(waiting).toHaveLength(2)
  expect(waiting.every(n => n.props?.color === 'yellow' && !n.props?.dimColor)).toBe(true)
  const jobs = nodes.filter(n => n.type === 'Text' && n.props?.wrap === 'truncate-end' && /外部工作|子代理/.test(flatText(n)))
  expect(jobs.map(flatText)).toEqual(['0m10s  codex  外部工作','running  Explore  子代理0','waiting for you  Explore  子代理1','idle  Explore  子代理2','pending  Explore  子代理3'])
  expect((jobs[1]!.children![0] as Drawn).props?.color).toBe('green')
  expect((jobs[3]!.children![0] as Drawn).props?.dimColor).toBe(true)
  expect((jobs[4]!.children![0] as Drawn).props?.dimColor).toBe(true)
  values.sessions[0]!.waitingUpdatedAt = -1
  await ui.redraw()
  expect(elements(await ui.drawn()).filter(n => n.type === 'Text' && flatText(n) === 'waiting for you')).toHaveLength(1)
})
