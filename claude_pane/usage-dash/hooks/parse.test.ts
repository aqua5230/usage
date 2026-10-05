import { describe, expect, test } from 'claude-code/testing'

import { formatElapsed, isShellBackgrounded, matchAgent, parseNotifications, backgroundTasks, liveBgTasks, STALE_MS } from './parse'

// Captured verbatim from a live background-task notification on Claude Code 2.1.288.
const NOTIFICATION = `<task-notification>
<task-id>bmfolkcj5</task-id>
<tool-use-id>toolu_01C2HgtbDDFTyLA6fh5X7oxY</tool-use-id>
<output-file>/private/tmp/claude-501/x/tasks/bmfolkcj5.output</output-file>
<status>completed</status>
<summary>Background command "Run a 3-second background sleep as the probe" completed (exit code 0)</summary>
</task-notification>`

describe('parseNotifications', () => {
  test('reads tool-use-id and status', () => {
    expect(parseNotifications(NOTIFICATION)).toEqual([
      { taskId: 'bmfolkcj5', toolUseId: 'toolu_01C2HgtbDDFTyLA6fh5X7oxY', status: 'completed' },
    ])
  })

  test('reads several notifications in one text', () => {
    const second = NOTIFICATION.replace('toolu_01C2HgtbDDFTyLA6fh5X7oxY', 'toolu_B').replace('completed', 'failed')
    expect(parseNotifications(`${NOTIFICATION}\n${second}`)).toEqual([
      { taskId: 'bmfolkcj5', toolUseId: 'toolu_01C2HgtbDDFTyLA6fh5X7oxY', status: 'completed' },
      { taskId: 'bmfolkcj5', toolUseId: 'toolu_B', status: 'failed' },
    ])
  })

  test('ignores ordinary prompts', () => {
    expect(parseNotifications('沒有跳出來')).toEqual([])
  })
})

describe('matchAgent', () => {
  const dispatches: [string, string][] = [
    ['codex exec -m gpt-6.1-sol --skip-git-repo-check -s workspace-write "fix it"', 'codex'],
    ['cd /Users/x/repo && codex exec "fix it" </dev/null', 'codex'],
    ['agy -p "research" --model gemini-3.8-flash-high --print-timeout 25m', 'agy'],
    ['grok --prompt-file /tmp/brief.md -m grok-4.7 --permission-mode acceptEdits --cwd /repo', 'grok'],
    ['muse exec --model muse-spark-1.3 --reasoning-effort medium --prompt-file b.md </dev/null', 'muse'],
    ['FOO=1 codex exec "x"', 'codex'],
    ['codex exec "$(cat <<\'EOF\'\nbrief\nEOF\n)"', 'codex'],
  ]
  for (const [command, agent] of dispatches) {
    test(command, () => expect(matchAgent(command)).toBe(agent))
  }

  const others = [
    'grep -n "codex exec" notes.md',
    'cat > count.py <<\'EOF\'\npat = re.compile(r"\\bcodex exec\\b")\ncodex exec x\nEOF',
    'codex exec --help',
    'echo agy -pretty',
    'ls ~/.codex/sessions',
  ]
  for (const command of others) {
    test(`ignores ${command}`, () => expect(matchAgent(command)).toBe(null))
  }
})

describe('isShellBackgrounded', () => {
  test('a trailing & backgrounds, && does not', () => {
    expect(isShellBackgrounded('codex exec "x" &')).toBe(true)
    expect(isShellBackgrounded('cd a && codex exec "x"')).toBe(false)
  })
})

describe('formatElapsed', () => {
  test('seconds, minutes, hours', () => {
    expect(formatElapsed(40_000)).toBe('40s')
    expect(formatElapsed(192_000)).toBe('3m12s')
    expect(formatElapsed(3_900_000)).toBe('1h05m')
  })
})


test('額外邊界：負數時間、空指令、空通知', () => {
  expect(formatElapsed(-1000)).toBe('0s')
  expect(matchAgent('')).toBe(null)
  expect(parseNotifications('')).toEqual([])
  expect(isShellBackgrounded('')).toBe(false)
})

test('matchAgent sees a dispatch after a heredoc brief', () => {
  expect(matchAgent(`SP=/tmp/x; cat > $SP/brief.md <<'EOF'\nrun codex exec here\nEOF\ncd /repo && codex exec -m gpt-6.1-sol "$(cat $SP/brief.md)" </dev/null`)).toBe('codex')
  expect(matchAgent(`cat > b.md <<'EOF'\ncodex exec x\nEOF\necho done`)).toBe(null)
})

test('Stop 清單排除子代理和派工，保留開始時間與指令備援', () => {
  const shell = {id:'shell',type:'shell',status:'running',description:'整理',command:'python scripts/auto_curate.py'}
  const tasks = [shell, {id:'child',type:'subagent',description:'讀檔'}, {id:'dispatch',type:'shell',description:'派工',command:'cd /repo && codex exec "fix"'}]
  const first = backgroundTasks(tasks,[],100)
  expect(first).toEqual([{id:'shell',type:'shell',label:'整理',start:100}])
  expect(backgroundTasks([{...shell,description:''}],first,200)).toEqual([{id:'shell',type:'shell',label:shell.command,start:100}])
  expect(backgroundTasks([...tasks,{id:'new',type:'monitor',description:'監看'}],first,200)[1]!.start).toBe(200)
  expect(backgroundTasks([],first,200)).toEqual([])
  expect(liveBgTasks(first,100 + STALE_MS - 1)).toEqual(first)
  expect(liveBgTasks(first,100 + STALE_MS)).toEqual([])
  expect(backgroundTasks(tasks,first,100 + STALE_MS)).toEqual([])
})

test('通知可只有 task-id，舊 tool-use-id 格式照常解析', () => {
  expect(parseNotifications('<task-notification><task-id>shell</task-id><status>completed</status></task-notification>')).toEqual([{taskId:'shell',status:'completed'}])
  expect(parseNotifications('<task-notification><tool-use-id>run</tool-use-id><status>failed</status></task-notification>')).toEqual([{toolUseId:'run',status:'failed'}])
  expect(parseNotifications('<task-notification><task-id>shell</task-id></task-notification>')).toEqual([])
})
