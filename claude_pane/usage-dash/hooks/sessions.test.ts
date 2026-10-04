import { expect, test } from 'claude-code/testing'
import { parseSession, isBusy, newest, sessionStatus, parseLiveSession, liveSessions, tasklistPids, toSession } from './sessions'
test('斷行跳過、最後標題優先、來源保留', () => {
  expect(parseSession('broken\n{"type":"ai-title","aiTitle":"舊標題"}\n{"type":"ai-title","aiTitle":"新標題","entrypoint":"cli"}\n{"type":"last-prompt","lastPrompt":"最後問題","entrypoint":"other"}')).toEqual({title:'新標題',source:'other'})
})
test('最後問題、空字串、無標題、桌面', () => {
  expect(parseSession('{"type":"last-prompt","lastPrompt":"第一"}\n{"type":"last-prompt","lastPrompt":"第二","entrypoint":"claude-desktop"}')).toEqual({title:'第二',source:'Desktop'})
  expect(parseSession('{"type":"ai-title","aiTitle":""}\n{"type":"last-prompt","lastPrompt":""}')).toEqual({title:'(untitled)',source:''})
  expect(parseSession('')).toEqual({title:'(untitled)',source:''})
  expect(newest([])).toEqual([])
})
test('狀態決定忙閒、時間缺省與名稱備援', () => {
  const row = parseLiveSession('{"pid":1,"sessionId":"one","name":"名稱","entrypoint":"cli","status":"busy","updatedAt":0}')!
  expect(row.statusUpdatedAt).toBe(0)
  expect(isBusy(toSession(row))).toBe(true)
  expect(sessionStatus(toSession(row),180000)).toBe('Busy')
  expect(sessionStatus(toSession({...row,status:'idle'}),180000)).toBe('Idle 3m ago')
  expect(isBusy(toSession({...row,status:'other'}))).toBe(false)
  expect(toSession(row).title).toBe('名稱')
  expect(toSession(row,'{"type":"ai-title","aiTitle":"標題","entrypoint":"other"}').source).toBe('(no project)')
  expect(toSession({...row,entrypoint:'claude-desktop'}).source).toBe('(no project) · Desktop')
  expect(toSession({...row,entrypoint:'other'}).source).toBe('(no project) · Desktop')
  expect(sessionStatus(toSession({...row,status:'idle',statusUpdatedAt:200000}),180000)).toBe('Idle just now')
})
test('壞 JSON 與無效資料跳過、死 pid 與空資料', () => {
  for (const text of ['broken','null','{}','{"pid":-1}','{"pid":1,"sessionId":"one","updatedAt":"bad"}']) expect(parseLiveSession(text)).toBeNull()
  const row = parseLiveSession('{"pid":1,"sessionId":"one","updatedAt":0}')!
  expect(liveSessions([row], ' 2\n')).toEqual([])
  expect(liveSessions([row], '')).toEqual([])
  expect(liveSessions([], '')).toEqual([])
  expect(liveSessions([row], ' 1\n')).toEqual([row])
})
test('tasklist PID 與 Windows 專案路徑', () => {
  expect(tasklistPids('\"claude.exe\",\"1864\",\"Console\"\n\"other.exe\",\"9\",\"Console\"')).toBe('1864 9')
  expect(tasklistPids('\"claude.exe\",\"1864\",\"Console\"\r\n')).toBe('1864')
  expect(tasklistPids('')).toBe('')
  expect(tasklistPids('\"含,逗號.exe\",\"1864\",\"Console\"')).toBe('1864')
  const row = parseLiveSession('{\"pid\":1,\"sessionId\":\"one\",\"entrypoint\":\"cli\",\"cwd\":\"C:\\\\Users\\\\USER\\\\Desktop\\\\GitHub\",\"updatedAt\":0}')!
  expect(toSession(row).source).toBe('GitHub')
  expect(toSession({...row,cwd:'C:\\Users\\USER\\Desktop\\GitHub\\'}).source).toBe('GitHub')
})
test('忙在前、同組時間新在前、不限八筆', () => {
  const rows = Array.from({length:10},(_,i) => ({id:String(i),title:'',source:'',mtimeMs:i,pid:i+1,status:i < 2 ? 'busy' : 'idle'}))
  expect(newest(rows).map(s => s.id)).toEqual(['1','0','9','8','7','6','5','4','3','2'])
})

 test('專案名稱、桌面、紀錄 cwd 與剛剛邊界', () => {
  const row = parseLiveSession('{"pid":1,"sessionId":"one","entrypoint":"cli","cwd":"/Users/x/usage/","updatedAt":0}')!
  expect(toSession(row).source).toBe('usage')
  expect(toSession({...row,cwd:'/'}).source).toBe('/')
  expect(toSession({...row,cwd:'',entrypoint:'claude-desktop'}).source).toBe('(no project) · Desktop')
  expect(toSession({...row,cwd:''},'{"cwd":"/Users/x/project"}').source).toBe('project')
  expect(sessionStatus(toSession(row),59000)).toBe('Idle just now')
  expect(sessionStatus(toSession(row),60000)).toBe('Idle 1m ago')
})
