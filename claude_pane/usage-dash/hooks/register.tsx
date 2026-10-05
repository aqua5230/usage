import { t, configure, statusArgv } from './strings'
import { atom, read, update } from 'claude-code'
import type { Hook, Register } from 'claude-code'
import type { Run, Session } from '../types'
import { matchAgent, isShellBackgrounded, parseNotifications, backgroundTasks, liveBgTasks, STALE_MS } from './parse'
import { parseQuota, hideAgents, byTightest, showsUnavailable, effectivePercent, dockQuotaLine, staleAge, refreshedAgo } from './quota'
import { compactLines } from './compact'
import { parseLiveSession, liveSessions, tasklistPids, toSession, newest, isBusy, waitingText, settleNotifications, sessionMark } from './sessions'
import { contextPercent, contextColor, parseContext, staleContext, completedAgo, isWaiting, visibleAgents, backgroundCount, visibleRuns } from './display'
const PANE = 'usage-dash'
const quotas = atom({ plugin: 'usage-dash', key: 'quotas' } as const, { agents: {} })
const updated = atom({ plugin: 'usage-dash', key: 'updated' } as const, null)
const quotaError = atom({ plugin: 'usage-dash', key: 'quotaError' } as const, '')
const sessions = atom({ plugin: 'usage-dash', key: 'sessions' } as const, [])
const pendingToasts = atom({ plugin: 'usage-dash', key: 'pendingToasts' } as const, [])
const sessionError = atom({ plugin: 'usage-dash', key: 'sessionError' } as const, '')
const agents = atom({ plugin: 'usage-dash', key: 'agents' } as const, [])
const runs = atom({ plugin: 'usage-dash', key: 'runs' } as const, [])
const bgTasks = atom({ plugin: 'usage-dash', key: 'bgTasks' } as const, [])
const collapsed = atom({ plugin: 'usage-dash', key: 'collapsed' } as const, { quota: false, sessions: false, runs: false })
const more = atom({ plugin: 'usage-dash', key: 'more' } as const, false)
const moreRuns = atom({ plugin: 'usage-dash', key: 'moreRuns' } as const, false)
type Dollar = Parameters<Hook<'session.start'>>[0]
const KEEP_DONE_MS = 300000
function isVisible(r: Run, now: number): boolean { return r.end === null ? now - r.start < STALE_MS : now - r.end < KEEP_DONE_MS }
async function getHome($: Dollar) { return (await $.env.get('HOME')) || (await $.env.get('USERPROFILE')) }
function clearLater($: Dollar) {
  $.clock.after(KEEP_DONE_MS + 1000, async () => {
    const now = await $.clock.now()
    await update($, runs, list => list.filter(r => isVisible(r, now)))
    await reportContext($, null)
  })
}
async function finish($: Dollar, text: string) {
  const done = parseNotifications(text)
  if (!done.length) return
  const end = await $.clock.now()
  await update($, runs, list => list.map(r => {
    const d = done.find(x => x.toolUseId === r.id)
    return d && r.end === null ? { ...r, end, status: d.status } : r
  }))
  await update($, bgTasks, list => liveBgTasks(list.filter(task => !done.some(d => d.taskId === task.id)), end))
  await reportContext($, null)
  clearLater($)
}
async function refreshQuota($: Dollar) {
  const home = await getHome($)
  const failures: string[] = []
  const commands = statusArgv ? [statusArgv] : ['usage', ...(home ? [`${home}/.local/bin/usage`] : [])].map(executable => [executable, 'status', '--json'])
  for (const argv of commands) {
    try {
      const result = await $.process.run(argv, { timeoutMs: 10000 })
      if (result.exitCode !== 0) throw new Error(`${argv[0]}: ${result.stderr || t('exit_code', { code: result.exitCode })}`)
      const parsed = parseQuota(result.stdout)
      let preferences = ''
      try { if (home) preferences = await $.fs.read(`${home}/.claude/usage-preferences.json`) } catch { /* missing preferences are normal */ }
      const data = hideAgents(parsed, preferences)
      const now = await $.clock.now()
      await update($, quotas, () => data)
      await update($, updated, () => now)
      await update($, quotaError, () => '')
      return
    } catch (error) { failures.push(String(error)) }
  }
  await update($, quotaError, () => t('quota_error', { error: failures.join('; ') }))
}
async function reportContext($: Dollar, waiting: boolean | null = false) {
  try {
    const home = await getHome($), sessionId = await $.session.id()
    if (!home || !/^[A-Za-z0-9_-]+$/.test(sessionId)) return
    const directory = `${home}/.usage/claude-pane/live`
    const path = `${directory}/${sessionId}.json`
    const now = await $.clock.now()
    const jobs = backgroundCount((await read($, runs)).filter(r => isVisible(r, now)), visibleAgents(await read($, agents)), liveBgTasks(await read($, bgTasks), now))
    let previous: ReturnType<typeof parseContext> = null
    try { previous = parseContext(await $.fs.read(path)) } catch { /* no previous context is normal */ }
    if (waiting === null && previous?.jobs === jobs) return
    let percent = previous?.percent
    try { percent = contextPercent((await $.session.usage()).context.percent) ?? percent } catch { /* waiting can be reported without usage */ }
    await $.fs.write(path, JSON.stringify({ sessionId, percent, waiting: waiting ?? previous?.waiting ?? false, jobs, updatedAt: now }))
  } catch { /* live reporting is best effort, as requested */ }
}
async function readContexts($: Dollar, directory: string, rows: Session[]) {
  const openIds = new Set(rows.map(row => row.id)), now = await $.clock.now()
  try {
    for (const file of await $.fs.list(directory)) {
      if (file.kind !== 'file' || file.isLink || !/^[A-Za-z0-9_-]+\.json$/.test(file.name)) continue
      const sessionId = file.name.slice(0, -5), path = `${directory}/${file.name}`
      try {
        const context = parseContext(await $.fs.read(path))
        if (!context || context.sessionId !== sessionId) continue
        const row = rows.find(row => row.id === sessionId)
        if (row) {
          row.contextPercent = context.percent
          row.jobs = context.jobs
          if (context.waiting !== undefined) {
            row.waiting = context.waiting
            row.waitingUpdatedAt = context.updatedAt
          }
        }
        if (staleContext(sessionId, Math.max(file.mtimeMs, context.updatedAt), openIds, now)) {
          if ((await $.env.get('OS')) === 'Windows_NT') await $.process.run(['cmd', '/d', '/c', 'del', '/f', '/q', path.replaceAll('/', '\\')])
          else await $.process.run(['rm', '-f', path])
        }
      } catch { /* unavailable live records do not affect the session list */ }
    }
  } catch { /* a missing live directory is normal before the first report */ }
}
async function refreshSessions($: Dollar) {
  const failures: string[] = []
  try {
    const home = await getHome($)
    if (!home) throw new Error(t('home_missing'))
    const directory = `${home}/.claude/sessions`
    const candidates = []
    for (const file of await $.fs.list(directory)) {
      if (!file.name.endsWith('.json')) continue
      try {
        const row = parseLiveSession(await $.fs.read(`${directory}/${file.name}`))
        if (row) candidates.push(row)
      } catch (error) { failures.push(`${file.name}：${String(error)}`) }
    }
    let psOutput = ''
    if (candidates.length) {
      try {
        if ((await $.env.get('OS')) === 'Windows_NT') {
          const result = await $.process.run(['tasklist', '/FO', 'CSV', '/NH'])
          if (result.exitCode === 0) psOutput = tasklistPids(result.stdout)
        } else {
          const result = await $.process.run(['ps', '-o', 'pid=', '-p', candidates.map(row => row.pid).join(',')])
          if (result.exitCode === 0) psOutput = result.stdout
        }
      } catch { /* ps failure means no live processes */ }
    }
    const rows: Session[] = []
    for (const row of liveSessions(candidates, psOutput)) {
      let transcript = ''
      try {
        if ((await $.env.get('OS')) === 'Windows_NT') {
          let path = ''
          for (const dir of await $.fs.list(`${home}/.claude/projects`)) {
            const candidate = `${home}/.claude/projects/${dir.name}/${row.sessionId}.jsonl`
            if (dir.kind === 'dir' && await $.fs.exists(candidate)) { path = candidate; break }
          }
          if (path) {
            if ((await $.fs.stat(path)).size <= 4 * 1024 * 1024) {
              transcript = (await $.fs.read(path)).slice(-262144)
            } else {
              const result = await $.process.run(['findstr', '/L', '/C:ai-title', '/C:last-prompt', path.replaceAll('/', '\\')])
              if (result.exitCode === 0) transcript = result.stdout
            }
          }
        } else {
          const found = await $.process.run(['/bin/sh', '-c', 'ls "$1"/*/"$2".jsonl 2>/dev/null | head -1', 'sh', `${home}/.claude/projects`, row.sessionId])
          const path = found.exitCode === 0 ? found.stdout.trim() : ''
          if (path) {
            const result = await $.process.run(['tail', '-c', '262144', path])
            if (result.exitCode !== 0) throw new Error(result.stderr || t('exit_code', { code: result.exitCode }))
            transcript = result.stdout
          }
        }
      } catch (error) { failures.push(`${row.sessionId}：${String(error)}`) }
      rows.push(toSession(row, transcript))
    }
    await readContexts($, `${home}/.usage/claude-pane/live`, rows)
    const previous = await read($, sessions), currentId = await $.session.id()
    const settled = settleNotifications(await read($, pendingToasts), previous, rows, currentId)
    await update($, sessions, () => newest(rows))
    await update($, pendingToasts, () => settled.pending)
    for (const { session, kind } of settled.toast) {
      const title = session.title.length > 40 ? `${session.title.slice(0,40)}…` : session.title
      $.ui.toast(t(`session_${kind}`, { title }), { timeoutMs: 8000 })
    }
  } catch (error) { failures.push(String(error)) }
  await update($, sessionError, () => failures.length ? t('session_error', { error: failures.join('; ') }) : '')
}
async function refreshAgents($: Dollar) {
  let list: Awaited<ReturnType<Dollar['agent']['list']>> = []
  try { list = await $.agent.list() } catch { /* unavailable agents are an empty list */ }
  const now = await $.clock.now()
  await update($, bgTasks, tasks => liveBgTasks(tasks, now))
  await update($, agents, () => visibleAgents(list))
  await reportContext($, null)
}
async function refreshSessionLists($: Dollar) {
  await refreshAgents($)
  await refreshSessions($)
}
let quotaTimer: { cancel(): void } | undefined
let sessionTimer: { cancel(): void } | undefined
let redrawTimer: { cancel(): void } | undefined
export const register: Register = (on) => {
  on('session.start', async ($, e, next) => {
    configure()
    try {
      const root = $.plugin.root.replace(/[\\/]\.claude-plugin[\\/]?$/, '')
      const path = `${root}/usage-pane.json`
      if (await $.fs.exists(path)) {
        const value = JSON.parse(await $.fs.read(path))
        if (!value || typeof value.strings !== 'object' || value.strings === null ||
            Array.isArray(value.strings) || !Object.values(value.strings).every(v => typeof v === 'string') ||
            !Array.isArray(value.status_argv) || !value.status_argv.length ||
            !value.status_argv.every((v: unknown) => typeof v === 'string' && v.length)) {
          throw new Error(t('invalid_sidecar'))
        }
        configure(value)
      }
    } catch (error) {
      await $.ui.log(t('sidecar_error', { error: String(error) }))
    }
    await $.command.register({ name: PANE, description: t('description') })
    void $.ui.open({ id: PANE, title: t('title') })
    quotaTimer?.cancel(); sessionTimer?.cancel(); redrawTimer?.cancel()
    quotaTimer = $.clock.every(60000, () => refreshQuota($))
    sessionTimer = $.clock.every(15000, () => refreshSessionLists($))
    redrawTimer = $.clock.every(1000, () => $.ui.invalidate('ui.render'))
    await reportContext($)
    await refreshQuota($)
    await refreshSessionLists($)
    return next(e)
  })
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    await reportContext($)
    return result
  })
  on('classic.Stop', async ($, e, next) => {
    const result = await next(e)
    const now = await $.clock.now()
    await update($, bgTasks, list => backgroundTasks(e.background_tasks ?? [], list, now))
    await reportContext($, null)
    return result
  })
  on('classic.PermissionRequest', async ($, e, next) => {
    await reportContext($, true)
    return next(e)
  })
  on('classic.Notification', async ($, e, next) => {
    if (e.notification_type === 'permission_prompt' || e.notification_type === 'elicitation_dialog') await reportContext($, true)
    return next(e)
  })
  on('classic.Elicitation', async ($, e, next) => {
    await reportContext($, true)
    return next(e)
  })
  on('classic.PostToolUse', async ($, e, next) => {
    await reportContext($)
    return next(e)
  })
  on('classic.PermissionDenied', async ($, e, next) => {
    await reportContext($)
    return next(e)
  })
  on('classic.ElicitationResult', async ($, e, next) => {
    await reportContext($)
    return next(e)
  })
  on('command.run', { command: PANE }, async $ => {
    await $.ui.open({ id: PANE, title: t('title') })
    return { text: t('opened') }
  })
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const agent = matchAgent(e.command)
    if (agent === null) return next(e)
    const start = await $.clock.now()
    const run: Run = { id: e.tool_use_id ?? `run-${start}`, agent, label: (e.description ?? '').slice(0,24), start, end: null, status: 'running' }
    await update($, runs, list => [...list.filter(r => isVisible(r,start)), run])
    await reportContext($, null)
    const ran = await next(e)
    if (ran.deny !== undefined) {
      await update($, runs, list => list.filter(r => r.id !== run.id))
      await reportContext($, null)
      return ran
    }
    const result = ran.result as { backgroundTaskId?: string } | undefined
    if (result?.backgroundTaskId === undefined) {
      const end = await $.clock.now()
      const status = isShellBackgrounded(e.command) ? 'launched' : ran.isError ? 'failed' : 'completed'
      await update($, runs, list => list.map(r => r.id === run.id ? { ...r, end, status } : r))
      await reportContext($, null)
      clearLater($)
    }
    return ran
  })
  on('prompt.submit', async ($, e, next) => {
    await reportContext($)
    if (e.origin.kind === 'task-notification') await finish($, e.text)
    return next(e)
  })
  on('session.receive', async ($, e, next) => {
    if (e.origin.kind === 'task-notification') await finish($, e.text)
    return next(e)
  })
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const now = await $.clock.now()
    const data = await read($, quotas), list = await read($, sessions), fold = await read($, collapsed)
    const shown = (await read($, runs)).filter(r => isVisible(r,now))
    const expanded = await read($, more), last = await read($, updated), runsExpanded = await read($, moreRuns)
    const qe = await read($, quotaError), se = await read($, sessionError)
    const current = await $.session.id()
    const agentList = visibleAgents(await read($, agents))
    const tasks = liveBgTasks(await read($, bgTasks), now)
    const jobs = backgroundCount(shown, agentList, tasks)
    const running = shown.filter(r => r.end === null).length + tasks.length
    if (e.props.placement === 'inline') {
      return <Box flexDirection="column">
        {compactLines(data,list,running,now,last).map((line,i) => <Text key={String(i)} wrap="wrap">
          {line.length ? line.map((part,j) => <Text key={String(j)} color={part.color} dimColor={!part.color} bold={part.bold}>{part.text}</Text>) : <Text dimColor>{' '}</Text>}
        </Text>)}
      </Box>
    }
    return <Box flexDirection="column">
      <Box flexDirection="column">
      <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1}>
      {!fold.quota && <Box flexDirection="column">
        {byTightest(data, ['claude-code','codex','antigravity','grok'], now, last === null ? 0 : (now-last)/1000).map(key => {
          const agent = data.agents[key]
          if (!agent || (!agent.available && !showsUnavailable(key, agent.reason))) return null
          const name = key === 'claude-code' ? 'Claude' : key === 'codex' ? 'Codex' : key === 'antigravity' ? 'agy' : 'Grok'
          if (!agent.available) return <Text key={key}><Text color={key === 'claude-code' ? '#d97757' : key === 'codex' ? '#10a37f' : key === 'antigravity' ? '#4285f4' : 'white'} bold={key === 'grok'}>{name.padEnd(8)}</Text><Text dimColor>{t(`unavailable_${agent.reason ?? 'no_data'}`)}</Text></Text>
          const age = staleAge(agent.age_seconds ?? 0, now, last)
          const groups = agent.groups ?? [{ name: '', five_hour: agent.five_hour, seven_day: agent.seven_day }]
          const rows = groups.flatMap(group => [
            ...(groups.length > 1 && group.name ? [[group.name === 'GEMINI MODELS' ? 'Gemini' : group.name === 'CLAUDE AND GPT MODELS' ? 'Claude / GPT' : group.name, undefined] as const] : []),
            ...([[t('five_hour'),group.five_hour],[t('week'),group.seven_day],[t('period'),agent.period]] as const).filter(([,window]) => window),
          ])
          return <Box key={key} flexDirection="column">
            {rows.map(([label,window],i) => {
              const line = window ? dockQuotaLine(label,window,now,last === null ? 0 : (now-last)/1000,e.props.bodyColumns) : null
              // Under 50% stays gray so only the windows worth watching carry color.
              const color = window && effectivePercent(window,now,last === null ? 0 : (now-last)/1000) >= 50 ? line?.color : undefined
              return <Text key={String(i)}><Text color={key === 'claude-code' ? '#d97757' : key === 'codex' ? '#10a37f' : key === 'antigravity' ? '#4285f4' : 'white'} bold={key === 'grok'}>{i === 0 ? `${name.padEnd(8)}` : '        '}</Text><Text dimColor>{line ? line.label : label}</Text>{line && <Text color={color} dimColor={!color}>{line.filled}</Text>}{line && <Text dimColor>{line.empty}</Text>}{line && ' '}{line && <Text color={color} dimColor={!color}>{line.percent}</Text>}{line && <Text dimColor>{line.countdown}</Text>}{i === 0 && age && <Text color="yellow">{age}</Text>}</Text>
            })}
          </Box>
        })}
        {!Object.keys(data.agents).length && <Text dimColor>{t('none')}</Text>}
        {qe && <Text color="red">{qe}</Text>}
      </Box>}
      </Box>
      <Box position="absolute" top={0} left={2} right={2} justifyContent="space-between"><Button key="quota" plain label={`[ ${fold.quota ? '▸' : '▾'} ${t('quota')} ]`} onPress={() => update($, collapsed, v => ({ ...v, quota: !v.quota }))} /></Box>
      </Box>
      <Box flexDirection="column">
      <Box flexDirection="column" borderStyle="round" borderColor="blue" paddingX={1}>
      {!fold.sessions && <Box flexDirection="column">
        {list.slice(0,expanded ? list.length : 4).map(s => {
          const waiting = s.status === 'waiting' || isWaiting({ waiting: s.waiting, updatedAt: s.waitingUpdatedAt ?? 0 }, now), mark = sessionMark(s, waiting, now)
          return <Box key={s.id} flexDirection="column">
            <Box justifyContent="space-between"><Box flexShrink={1}><Text wrap="truncate-end"><Text color={mark.color} dimColor={!mark.color}>{mark.text}</Text><Text dimColor>{` ${s.source}${s.source ? ' ' : ''}`}</Text>{s.id === current && <Text color="cyan">{t('here')}</Text>}{s.title || t('untitled')}</Text></Box>{s.contextPercent !== undefined && <Box flexShrink={0} marginLeft={1}><Text color={contextColor(s.contextPercent)} dimColor={contextColor(s.contextPercent) === undefined}>{`${s.contextPercent}%`}</Text></Box>}</Box>
            {(waiting || s.preview) && <Box justifyContent="space-between"><Box flexShrink={1}><Text wrap="truncate-end">{'    '}{waiting && <Text color="yellow">{waitingText(s.waitingFor)}</Text>}{s.preview && <Text dimColor>{`${waiting ? ' · ' : ''}${s.preview}`}</Text>}</Text></Box></Box>}
          </Box>
        })}
        {!list.length && <Text dimColor>{t('none')}</Text>}
        {list.length > 4 && <Button key="more" plain label={expanded ? `[ − ${t('less')} ]` : `[ + ${t('more', { count: list.length-4 })} ]`} onPress={() => update($, more, v => !v)} />}
        {se && <Text color="red">{se}</Text>}
      </Box>}
      </Box>
      <Box position="absolute" top={0} left={2} right={2} justifyContent="space-between">
        <Button key="sessions" plain label={`[ ${fold.sessions ? '▸' : '▾'} ${t('sessions')} ]`} onPress={() => update($, collapsed, v => ({ ...v, sessions: !v.sessions }))} />
        <Text>{' '}<Text dimColor>{t('busy_count', { count: list.filter(s => isBusy(s)).length, total: list.length })}</Text>{' '}</Text>
      </Box>
      </Box>
      <Box flexDirection="column">
      <Box flexDirection="column" borderStyle="round" borderColor="yellow" paddingX={1}>
      {!fold.runs && <Box flexDirection="column">
        {visibleRuns(shown, runsExpanded, tasks).rows.map(r => {
          const done = r.end !== null
          const seconds = Math.max(0, Math.floor(((r.end ?? now)-r.start)/1000))
          const elapsed = t('elapsed', { minutes: Math.floor(seconds/60), seconds: String(seconds%60).padStart(2,'0') })
          const prefix = done ? `${r.status === 'completed' ? '✓' : r.status === 'launched' ? '↗' : '✗'} ` : ''
          return <Text key={r.id} dimColor={done} wrap="truncate-end"><Text color={done ? undefined : 'green'}>{`${prefix}${elapsed}`}</Text>{'  '}<Text color={done ? undefined : 'cyan'}>{r.agent}</Text>{`  ${r.label}`}<Text dimColor>{completedAgo(r,now)}</Text></Text>
        })}
        {agentList.map(agent => <Text key={`agent-${agent.id}`} wrap="truncate-end"><Text color={agent.status === 'running' ? 'green' : agent.status === 'waiting' ? 'yellow' : undefined} dimColor={agent.status === 'idle' || agent.status === 'pending'}>{agent.status === 'waiting' ? t('waiting') : t(`agent_${agent.status}`)}</Text>{'  '}<Text color="cyan">{agent.type}</Text>{`  ${agent.description}`}</Text>)}
        {(runsExpanded || visibleRuns(shown, false, tasks).hiddenDone > 0) && <Button key="moreRuns" plain label={runsExpanded ? `[ − ${t('less')} ]` : `[ + ${t('more', { count: visibleRuns(shown, false, tasks).hiddenDone })} ]`} onPress={() => update($, moreRuns, v => !v)} />}
        {!shown.length && !agentList.length && !tasks.length && <Text dimColor>{t('none')}</Text>}
      </Box>}
      </Box>
      <Box position="absolute" top={0} left={2} right={2} justifyContent="space-between">
        <Button key="runs" plain label={`[ ${fold.runs ? '▸' : '▾'} ${t('runs')} ]`} onPress={() => update($, collapsed, v => ({ ...v, runs: !v.runs }))} />
        <Text>{' '}<Text color={jobs > 0 ? 'yellow' : undefined} dimColor={jobs === 0}>{jobs}</Text>{' '}</Text>
      </Box>
      </Box>
      <Box justifyContent="flex-end"><Text dimColor>{refreshedAgo(now, last)}</Text></Box>
    </Box>
  })
}
