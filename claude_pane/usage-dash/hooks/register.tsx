import { t, configure, statusArgv } from './strings'
import { atom, read, update } from 'claude-code'
import type { Hook, Register } from 'claude-code'
import type { Run, Session } from '../types'
import { matchAgent, isShellBackgrounded, parseNotifications } from './parse'
import { parseQuota, hideAgents, dockQuotaLine, staleAge, refreshedAgo } from './quota'
import { compactLines } from './compact'
import { parseLiveSession, liveSessions, tasklistPids, toSession, newest, isBusy, sessionStatus } from './sessions'
import { contextPercent, contextColor, parseContext, staleContext, completedAgo, isWaiting, visibleAgents, backgroundCount } from './display'
const PANE = 'usage-dash'
const quotas = atom({ plugin: 'usage-dash', key: 'quotas' } as const, { agents: {} })
const updated = atom({ plugin: 'usage-dash', key: 'updated' } as const, null)
const quotaError = atom({ plugin: 'usage-dash', key: 'quotaError' } as const, '')
const sessions = atom({ plugin: 'usage-dash', key: 'sessions' } as const, [])
const sessionError = atom({ plugin: 'usage-dash', key: 'sessionError' } as const, '')
const agents = atom({ plugin: 'usage-dash', key: 'agents' } as const, [])
const runs = atom({ plugin: 'usage-dash', key: 'runs' } as const, [])
const collapsed = atom({ plugin: 'usage-dash', key: 'collapsed' } as const, { quota: false, sessions: false, runs: false })
const more = atom({ plugin: 'usage-dash', key: 'more' } as const, false)
type Dollar = Parameters<Hook<'session.start'>>[0]
const STALE_MS = 3600000
const KEEP_DONE_MS = 300000
function isVisible(r: Run, now: number): boolean { return r.end === null ? now - r.start < STALE_MS : now - r.end < KEEP_DONE_MS }
async function getHome($: Dollar) { return (await $.env.get('HOME')) || (await $.env.get('USERPROFILE')) }
function clearLater($: Dollar) {
  $.clock.after(KEEP_DONE_MS + 1000, async () => {
    const now = await $.clock.now()
    await update($, runs, list => list.filter(r => isVisible(r, now)))
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
async function reportContext($: Dollar, waiting = false) {
  try {
    const home = await getHome($), sessionId = await $.session.id()
    if (!home || !/^[A-Za-z0-9_-]+$/.test(sessionId)) return
    const directory = `${home}/.usage/claude-pane/live`
    const path = `${directory}/${sessionId}.json`
    let percent: number | undefined
    try { percent = parseContext(await $.fs.read(path))?.percent } catch { /* no previous context is normal */ }
    try { percent = contextPercent((await $.session.usage()).context.percent) ?? percent } catch { /* waiting can be reported without usage */ }
    await $.fs.write(path, JSON.stringify({ sessionId, percent, waiting, updatedAt: await $.clock.now() }))
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
    await update($, sessions, () => newest(rows))
  } catch (error) { failures.push(String(error)) }
  await update($, sessionError, () => failures.length ? t('session_error', { error: failures.join('; ') }) : '')
}
async function refreshAgents($: Dollar) {
  let list: Awaited<ReturnType<Dollar['agent']['list']>> = []
  try { list = await $.agent.list() } catch { /* unavailable agents are an empty list */ }
  await update($, agents, () => visibleAgents(list))
}
async function refreshSessionLists($: Dollar) {
  await Promise.all([refreshSessions($), refreshAgents($)])
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
    const ran = await next(e)
    if (ran.deny !== undefined) {
      await update($, runs, list => list.filter(r => r.id !== run.id))
      return ran
    }
    const result = ran.result as { backgroundTaskId?: string } | undefined
    if (result?.backgroundTaskId === undefined) {
      const end = await $.clock.now()
      const status = isShellBackgrounded(e.command) ? 'launched' : ran.isError ? 'failed' : 'completed'
      await update($, runs, list => list.map(r => r.id === run.id ? { ...r, end, status } : r))
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
    const expanded = await read($, more), last = await read($, updated)
    const qe = await read($, quotaError), se = await read($, sessionError)
    const current = await $.session.id()
    const agentList = visibleAgents(await read($, agents))
    const jobs = backgroundCount(shown, agentList)
    const running = shown.filter(r => r.end === null).length
    if (e.props.placement === 'inline') {
      return <Box flexDirection="column">
        {compactLines(data,list,running,now,last).map((line,i) => <Text key={String(i)} wrap="wrap">
          {line.length ? line.map((part,j) => <Text key={String(j)} color={part.color} dimColor={!part.color} bold={part.bold}>{part.text}</Text>) : <Text dimColor>{' '}</Text>}
        </Text>)}
      </Box>
    }
    return <Box flexDirection="column">
      <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1}>
      <Box justifyContent="space-between"><Button key="quota" plain label={`[ ${fold.quota ? '▸' : '▾'} ${t('quota')} ]`} onPress={() => update($, collapsed, v => ({ ...v, quota: !v.quota }))} /></Box>
      {!fold.quota && <Box flexDirection="column">
        {['claude-code','codex','antigravity','grok'].map(key => {
          const agent = data.agents[key]
          if (!agent?.available) return null
          const name = key === 'claude-code' ? 'Claude' : key === 'codex' ? 'Codex' : key === 'antigravity' ? 'agy' : 'Grok'
          const age = staleAge(agent.age_seconds ?? 0, now, last)
          const groups = agent.groups ?? [{ name: '', five_hour: agent.five_hour, seven_day: agent.seven_day }]
          return <Box key={key} flexDirection="column">
            <Box justifyContent="space-between">
              <Text><Text color={key === 'claude-code' ? '#d97757' : key === 'codex' ? '#10a37f' : key === 'antigravity' ? '#4285f4' : 'white'} bold={key === 'grok'}>{`▎ ${name}`}</Text><Text dimColor>{key === 'grok' && agent.tier ? ` ${agent.tier}` : ''}</Text>{age && <Text color="yellow">{age}</Text>}</Text>
              {agent.model && <Box flexShrink={1} marginLeft={1}><Text dimColor wrap="truncate-end">{agent.model}</Text></Box>}
            </Box>
            {groups.map((group,i) => <Box key={`${key}-${i}`} flexDirection="column">
              {group.name && <Text dimColor>{`  ${group.name === 'GEMINI MODELS' ? 'Gemini' : group.name === 'CLAUDE AND GPT MODELS' ? 'Claude / GPT' : group.name}`}</Text>}
              {([[t('five_hour'),group.five_hour],[t('week'),group.seven_day],[t('period'),agent.period]] as const).map(([label,window]) => {
                if (!window) return null
                const line = dockQuotaLine(label,window,now,last === null ? 0 : (now-last)/1000,e.props.bodyColumns)
                return <Text key={label}><Text dimColor>{`  ${line.label}`}</Text><Text color={line.color}>{line.filled}</Text><Text dimColor>{line.empty}</Text>{' '}<Text color={line.color}>{line.percent}</Text><Text dimColor>{line.countdown}</Text></Text>
              })}
            </Box>)}
          </Box>
        })}
        {!Object.keys(data.agents).length && <Text dimColor>{t('none')}</Text>}
        {qe && <Text color="red">{qe}</Text>}
      </Box>}
      </Box>
      <Box flexDirection="column" borderStyle="round" borderColor="blue" paddingX={1}>
      <Box justifyContent="space-between">
        <Button key="sessions" plain label={`[ ${fold.sessions ? '▸' : '▾'} ${t('sessions')} ]`} onPress={() => update($, collapsed, v => ({ ...v, sessions: !v.sessions }))} />
        <Text dimColor>{t('busy_count', { count: list.filter(s => isBusy(s)).length, total: list.length })}</Text>
      </Box>
      {!fold.sessions && <Box flexDirection="column">
        {list.slice(0,expanded ? list.length : 4).map(s => {
          const busy = isBusy(s)
          const waiting = isWaiting({ waiting: s.waiting, updatedAt: s.waitingUpdatedAt ?? 0 }, now)
          return <Box key={s.id} flexDirection="column">
            <Box justifyContent="space-between"><Box flexShrink={1}><Text wrap="truncate-end"><Text color={busy ? 'green' : undefined} dimColor={!busy}>●</Text><Text dimColor>{` ${s.source}${s.source ? ' ' : ''}`}</Text>{s.id === current && <Text color="cyan">{t('here')}</Text>}{s.title || t('untitled')}</Text></Box>{s.contextPercent !== undefined && <Box flexShrink={0} marginLeft={1}><Text color={contextColor(s.contextPercent)} dimColor={contextColor(s.contextPercent) === undefined}>{`${s.contextPercent}%`}</Text></Box>}</Box>
            <Box justifyContent="space-between"><Box flexShrink={1}><Text wrap="truncate-end">{'    '}<Text color={waiting ? 'yellow' : busy ? 'green' : undefined} dimColor={!waiting && !busy}>{waiting ? t('waiting') : sessionStatus(s,now)}</Text></Text></Box></Box>
          </Box>
        })}
        {!list.length && <Text dimColor>{t('none')}</Text>}
        {list.length > 4 && <Button key="more" plain label={expanded ? `[ − ${t('less')} ]` : `[ + ${t('more', { count: list.length-4 })} ]`} onPress={() => update($, more, v => !v)} />}
        {se && <Text color="red">{se}</Text>}
      </Box>}
      </Box>
      <Box flexDirection="column" borderStyle="round" borderColor="yellow" paddingX={1}>
      <Box justifyContent="space-between">
        <Button key="runs" plain label={`[ ${fold.runs ? '▸' : '▾'} ${t('runs')} ]`} onPress={() => update($, collapsed, v => ({ ...v, runs: !v.runs }))} />
        <Text color={jobs > 0 ? 'yellow' : undefined} dimColor={jobs === 0}>{jobs}</Text>
      </Box>
      {!fold.runs && <Box flexDirection="column">
        {shown.slice(-4).map(r => {
          const done = r.end !== null
          const seconds = Math.max(0, Math.floor(((r.end ?? now)-r.start)/1000))
          const elapsed = t('elapsed', { minutes: Math.floor(seconds/60), seconds: String(seconds%60).padStart(2,'0') })
          const prefix = done ? `${r.status === 'completed' ? '✓' : r.status === 'launched' ? '↗' : '✗'} ` : ''
          return <Text key={r.id} dimColor={done} wrap="truncate-end"><Text color={done ? undefined : 'green'}>{`${prefix}${elapsed}`}</Text>{'  '}<Text color={done ? undefined : 'cyan'}>{r.agent}</Text>{`  ${r.label}`}<Text dimColor>{completedAgo(r,now)}</Text></Text>
        })}
        {agentList.map(agent => <Text key={`agent-${agent.id}`} wrap="truncate-end"><Text color={agent.status === 'running' ? 'green' : agent.status === 'waiting' ? 'yellow' : undefined} dimColor={agent.status === 'idle' || agent.status === 'pending'}>{agent.status === 'waiting' ? t('waiting') : t(`agent_${agent.status}`)}</Text>{'  '}<Text color="cyan">{agent.type}</Text>{`  ${agent.description}`}</Text>)}
        {!shown.length && !agentList.length && <Text dimColor>{t('none')}</Text>}
      </Box>}
      </Box>
      <Box justifyContent="flex-end"><Text dimColor>{refreshedAgo(now, last)}</Text></Box>
    </Box>
  })
}
