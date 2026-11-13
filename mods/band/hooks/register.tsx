import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type { AgentState, AgentStore, Gauges, Range, Roster } from '../types'

import { type OpenCall, activityOf, withCall, withoutCall } from './calls'
import { bandRefreshMs } from './desktop'
import { EMPTY_GAUGES, isSameGauges, withCache, withCompaction, withTurn, withUsage } from './gauges'
import { DIRECT_GROUP, DIRECT_LABEL, EMPTY_ROSTER, EMPTY_STORE, type MainActivity, addAgent, type PendingUsage, applyPendingUsage, agentTypeName, closeOpen, lastEventAt, applyListing, MAIN_ID, endBackgroundTask, finishAgent, startBackgroundTask, isSameRoster, moveAgent, OWNER_QUESTION_TOOLS, moveMain, nextQuietChangeMs, newAgent, noteAgentKind, recordTurnUsage, rosterOf, sessionTotal } from './model'
import { nextLeaveMs } from './layout'
import { terminalSchemeOf, themeOf } from './format'
import { TICK_MS, frameAt } from './paint'
import { columnsToWidth } from './svg-band'
import { type Actions, type Painter, type Rows, buildBand } from './view'
import { buildDesktopBand } from './view-desktop'

const RECONCILE_MS = 1000

const FAIL_REASON_WORD: Partial<Record<string, string>> = { aborted: 'aborted', refusal: 'refused', error: 'error' }

const isFolded = atom({ plugin: 'harness-band', key: 'isFolded' } as const, false, { shape: 'isFolded-2' })
const range = atom({ plugin: 'harness-band', key: 'range' } as const, '1m')
const foldedGroups = atom({ plugin: 'harness-band', key: 'foldedGroups' } as const, [], { shape: 'foldedGroups-2' })
const agents = atom({ plugin: 'harness-band', key: 'agents' } as const, EMPTY_STORE, { shape: 'agents-3' })
const roster = atom({ plugin: 'harness-band', key: 'roster' } as const, EMPTY_ROSTER, { shape: 'roster-1' })
const gauges = atom({ plugin: 'harness-band', key: 'gauges' } as const, EMPTY_GAUGES, { shape: 'gauges-3' })
const turnStartedAt = atom({ plugin: 'harness-band', key: 'turnStartedAt' } as const, null)
const scheme = atom({ plugin: 'harness-band', key: 'scheme' } as const, 'light')

const describeCall = (call: { tool: string } & Record<string, unknown>): string => {
  const command = call['command']

  if (typeof command === 'string') {
    return command.split('\n')[0] ?? command
  }

  for (const field of ['file_path', 'path', 'pattern', 'url', 'description']) {
    const value = call[field]

    if (typeof value === 'string') {
      return `${call.tool} ${value}`
    }
  }

  return call.tool
}

const reportFailure = ($: EngineInterface, where: string, cause: unknown): void => {
  $.ui.log(`harness-band ${where}: ${cause instanceof Error ? cause.message : String(cause)}`, { to: 'debug' })
}

type Runtime = {
  painters: Map<string, Painter>
  requestId: string | null
  isTicking: boolean
  isReconciling: boolean
  timers: Timer[]
  store: AgentStore | null
  roster: Roster | null
  queue: Promise<void>
  refreshAt: number | null
  isDrawnByTree: boolean
  isClearing: boolean
  listedIds: Set<string>
  openCalls: Map<string, readonly OpenCall[]>
  callSerial: number
  pendingUsage: PendingUsage[]
}

const indexRows = (store: AgentStore | null): Rows => new Map([...(store?.main ? [store.main] : []), ...(store?.rows ?? [])].map(row => [row.id, row]))

const settlePendingUsage = async ($: EngineInterface, runtime: Runtime): Promise<void> => {
  const queued = [...runtime.pendingUsage]

  if (queued.length === 0) {
    return
  }

  let applied: readonly PendingUsage[] = []
  await mutateAgents($, runtime, (store, now) => {
    const result = applyPendingUsage(store, queued, now)
    applied = result.applied

    return result.store
  })
  runtime.pendingUsage = runtime.pendingUsage.filter(entry => !applied.includes(entry))
}

const mutateAgents = async ($: EngineInterface, runtime: Runtime, change: (store: AgentStore, now: number) => AgentStore): Promise<void> => {
  const run = async (): Promise<void> => {
    const now = await $.clock.now()

    if (runtime.store !== null && change(runtime.store, now) === runtime.store) {
      return
    }

    let written: AgentStore = EMPTY_STORE
    await update($, agents, current => {
      written = change(current, now)
      return written
    })

    runtime.store = written

    if (runtime.isDrawnByTree) {
      $.ui.invalidate('ui.render')
    }

    const wanted: Roster = rosterOf(written)

    if (runtime.roster === null || !isSameRoster(runtime.roster, wanted)) {
      runtime.roster = wanted
      await update($, roster, () => wanted)
    }
  }
  const queued = runtime.queue.then(run)
  runtime.queue = queued.catch(cause => reportFailure($, 'agents', cause))

  return queued
}

const setAgentState = ($: EngineInterface, runtime: Runtime, change: { id: string; state: AgentState; command: string | null; from?: AgentState }): Promise<void> => mutateAgents($, runtime, (store, now) => moveAgent(store, { ...change, now }))

const setMainActivity = ($: EngineInterface, runtime: Runtime, change: { activity: MainActivity; from?: AgentState }): Promise<void> => mutateAgents($, runtime, (store, now) => moveMain(store, { ...change, now }))

const writeGauges = async ($: EngineInterface, next: (current: Gauges) => Gauges): Promise<void> => {
  const current = await read($, gauges)
  const value = next(current)

  if (!isSameGauges(current, value)) {
    await update($, gauges, () => value)
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null

const backgroundTaskIdOf = (call: Record<string, unknown>, outcome: unknown): string | null => {
  if (call['tool'] !== 'Bash' || call['run_in_background'] !== true || !isRecord(outcome)) {
    return null
  }

  const output = outcome['result']

  if (isRecord(output) && typeof output['backgroundTaskId'] === 'string') {
    return output['backgroundTaskId']
  }

  return typeof call['tool_use_id'] === 'string' ? call['tool_use_id'] : null
}

const stoppedTaskIdOf = (call: Record<string, unknown>): string | null => {
  if (call['tool'] !== 'TaskStop' && call['tool'] !== 'KillShell') {
    return null
  }

  for (const field of ['task_id', 'shell_id']) {
    const value = call[field]

    if (typeof value === 'string') {
      return value
    }
  }

  return null
}

const FINISHED_NOTICE = /<status>\s*(completed|failed|killed|stopped)\s*<\/status>/
const NOTICE_TASK_ID = /<task-id>\s*([^<\s]+)\s*<\/task-id>/

const finishedTaskIdOf = (blocks: readonly unknown[]): string | null => {
  for (const block of blocks) {
    const text = isRecord(block) && typeof block['text'] === 'string' ? block['text'] : ''
    const taskId = text.includes('<task-notification') ? NOTICE_TASK_ID.exec(text)?.[1] : undefined

    if (taskId !== undefined && (FINISHED_NOTICE.test(text) || !text.includes('<status>'))) {
      return taskId
    }
  }

  return null
}

const noteBackgroundStart = async ($: EngineInterface, runtime: Runtime, input: { owner: string; call: Record<string, unknown>; outcome: unknown }): Promise<void> => {
  const taskId = backgroundTaskIdOf(input.call, input.outcome)

  if (taskId !== null) {
    await mutateAgents($, runtime, (store, now) => startBackgroundTask(store, { owner: input.owner, taskId, now }))
  }
}

const reconcile = async ($: EngineInterface, runtime: Runtime): Promise<void> => {
  if (runtime.isReconciling) {
    return
  }

  runtime.isReconciling = true

  try {
    const list = await $.agent.list()
    await mutateAgents($, runtime, (store, now) => applyListing(store, list, now, runtime.listedIds))

    for (const info of list) {
      runtime.listedIds.add(info.id)
    }

    await settlePendingUsage($, runtime)
  } finally {
    runtime.isReconciling = false
  }
}

const showOpenCalls = async ($: EngineInterface, runtime: Runtime, input: { owner: string; isEnd: boolean }): Promise<void> => {
  const activity = activityOf(runtime.openCalls.get(input.owner) ?? [])

  if (input.owner !== MAIN_ID) {
    await setAgentState($, runtime, { id: input.owner, ...activity, ...(input.isEnd ? { from: 'tool' as const } : {}) })

    return
  }

  for (const from of input.isEnd ? (['tool', 'waiting'] as const) : [undefined]) {
    await setMainActivity($, runtime, { activity, ...(from === undefined ? {} : { from }) })
  }
}

const stopTimers = (runtime: Runtime): void => {
  for (const timer of runtime.timers.splice(0)) {
    timer.cancel()
  }
}

const tick = async ($: EngineInterface, runtime: Runtime): Promise<void> => {
  const requestId = runtime.requestId

  if (runtime.isTicking || requestId === null) {
    return
  }

  runtime.isTicking = true

  try {
    const now = await $.clock.now()
    const frame = frameAt(now)

    if (runtime.refreshAt !== null && now >= runtime.refreshAt) {
      $.ui.invalidate('ui.render')
    }

    const store = await read($, agents)
    runtime.store = runtime.store ?? store
    const rows = indexRows(store)

    for (const [key, painter] of runtime.painters) {
      const cells = painter.paint(frame, rows)

      if (cells !== painter.last) {
        painter.last = cells
        await $.ui.blit({ requestId, key, cells })
      }
    }
  } finally {
    runtime.isTicking = false
  }
}

const startClocks = ($: EngineInterface, runtime: Runtime): void => {
  if (runtime.timers.length > 0) {
    return
  }

  runtime.timers.push($.clock.every(TICK_MS, () => void tick($, runtime).catch(cause => reportFailure($, 'tick', cause))))
  runtime.timers.push($.clock.every(RECONCILE_MS, () => void reconcile($, runtime).catch(cause => reportFailure($, 'reconcile', cause))))
}

export const register: Register = on => {
  const runtime: Runtime = {
    painters: new Map(),
    requestId: null,
    isTicking: false,
    isReconciling: false,
    timers: [],
    store: null,
    roster: null,
    queue: Promise.resolve(),
    refreshAt: null,
    isDrawnByTree: false,
    isClearing: false,
    listedIds: new Set(),
    pendingUsage: [],
    openCalls: new Map(),
    callSerial: 0,
  }

  on('session.start', async ($, event, next) => {
    const result = await next(event)

    if (!runtime.isClearing) {
      await mutateAgents($, runtime, (store, now) => closeOpen(store, store.main === null ? now : lastEventAt(store.main)))
    }

    runtime.isClearing = false
    const usage = await $.session.usage()
    await writeGauges($, current => withUsage(current, usage))
    const rows = await $.config.list()
    await update($, scheme, () => themeOf(rows.find(row => row.key === 'theme')?.value))
    startClocks($, runtime)

    return result
  })

  on('session.end', async ($, event, next) => {
    runtime.isClearing = event.reason === 'clear'

    if (event.reason === 'clear') {
      return next(event)
    }

    stopTimers(runtime)
    await mutateAgents($, runtime, (store, now) => closeOpen(store, now))
    await update($, turnStartedAt, () => null)

    return next(event)
  })

  on('config.set', { key: 'theme' }, async ($, event, next) => {
    const result = await next(event)
    const rows = await $.config.list()
    await update($, scheme, () => themeOf(rows.find(row => row.key === 'theme')?.value))

    return result
  })

  on('agent.spawn', async ($, event, next) => {
    startClocks($, runtime)
    const result = await next(event)

    if (result.agentId !== undefined) {
      const id = result.agentId
      const group = event.workflow === undefined ? DIRECT_GROUP : event.workflow.runId
      const groupLabel = event.workflow === undefined ? DIRECT_LABEL : `workflow ${event.workflow.runId.replace(/^wf_/, '').slice(0, 8)}`

      const type = agentTypeName(event.subagentType)
      const model = typeof result.model === 'string' ? result.model : undefined

      await mutateAgents($, runtime, (store, now) => noteAgentKind(addAgent(store, newAgent({ id, label: `${event.name ?? type}-${sessionTotal(store) + 1}`, group, groupLabel, now })), { id, type, model }))
    }

    await settlePendingUsage($, runtime)

    return result
  })

  on('turn.start', async ($, event, next) => {
    startClocks($, runtime)

    if (event.agentId === undefined) {
      const now = await $.clock.now()
      await update($, turnStartedAt, () => now)
      await setMainActivity($, runtime, { activity: { state: 'thinking', command: null } })
    } else {
      await setAgentState($, runtime, { id: event.agentId, state: 'thinking', command: null })
    }

    return next(event)
  })

  on('tool.call', async ($, event, next) => {
    startClocks($, runtime)
    const stoppedId = stoppedTaskIdOf(event)

    if (stoppedId !== null) {
      const outcome = await next(event)
      await mutateAgents($, runtime, (store, now) => endBackgroundTask(store, { taskId: stoppedId, now })).catch(cause => reportFailure($, 'background stop', cause))

      return outcome
    }

    const owner = event.agentId ?? MAIN_ID
    runtime.callSerial += 1
    const call: OpenCall = { token: runtime.callSerial, command: describeCall(event), isQuestion: owner === MAIN_ID && OWNER_QUESTION_TOOLS.includes(event.tool) }
    runtime.openCalls.set(owner, withCall(runtime.openCalls.get(owner) ?? [], call))
    await showOpenCalls($, runtime, { owner, isEnd: false }).catch(cause => reportFailure($, 'tool start', cause))

    try {
      const outcome = await next(event)
      await noteBackgroundStart($, runtime, { owner, call: event, outcome }).catch(cause => reportFailure($, 'background start', cause))

      return outcome
    } finally {
      runtime.openCalls.set(owner, withoutCall(runtime.openCalls.get(owner) ?? [], call.token))
      await showOpenCalls($, runtime, { owner, isEnd: true }).catch(cause => reportFailure($, 'tool end', cause))
    }
  })

  on('turn.complete', async ($, event, next) => {
    startClocks($, runtime)

    if (event.agentId === undefined) {
      await update($, turnStartedAt, () => null)
      await setMainActivity($, runtime, { activity: null })
      const usage = event.usage
      const calledAt = await $.clock.now()
      await writeGauges($, current => withTurn(usage === undefined ? current : withCache(current, usage, calledAt)))

      if (usage !== undefined) {
        await mutateAgents($, runtime, (store, now) => recordTurnUsage(store, { id: MAIN_ID, tokens: usage, model: usage.model, now }))
      }
    } else {
      const agentId = event.agentId
      const usage = event.usage
      const state = event.reason === 'answer' ? 'done' : 'failed'
      const reason = FAIL_REASON_WORD[event.reason]

      if (usage !== undefined) {
        runtime.pendingUsage.push({ id: agentId, tokens: usage, model: usage.model })
        await settlePendingUsage($, runtime)
      }

      await mutateAgents($, runtime, (store, now) => finishAgent(store, { id: agentId, state, now, ...(reason === undefined ? {} : { reason }) }))
    }

    return next(event)
  })

  on('session.append', async ($, event, next) => {
    const taskId = finishedTaskIdOf(event.message.content)

    if (taskId !== null) {
      await mutateAgents($, runtime, (store, now) => endBackgroundTask(store, { taskId, now })).catch(cause => reportFailure($, 'background end', cause))
    }

    return next(event)
  })

  on('session.measure', async ($, event, next) => {
    startClocks($, runtime)
    await writeGauges($, current => withUsage(current, event))

    return next(event)
  })

  on('session.compact', async ($, event, next) => {
    const result = await next(event)

    if (event.trigger !== 'precompute' && result.messages !== undefined && event.agentId === undefined) {
      const tokensBefore = result.tokensBefore
      await writeGauges($, current => withCompaction(current, tokensBefore))
    }

    return result
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, event, next) => {
    if (event.props.hasSurvey) {
      return next(event)
    }

    startClocks($, runtime)
    const ui = $.ui.resolve(event)
    const hasRaster = 'Raster' in ui
    const [folded, rangeValue, groups, rosterValue, gaugeValues, startedAt, schemeValue] = await Promise.all([read($, isFolded), read($, range), read($, foldedGroups), read($, roster), read($, gauges), read($, turnStartedAt), read($, scheme)])
    const store = hasRaster ? runtime.store : await read($, agents)
    const now = await $.clock.now()
    const actions: Actions = {
      toggleFold: () => void update($, isFolded, current => !current),
      setRange: (chosen: Range) => void update($, range, () => chosen),
      toggleGroup: (id: string) => void update($, foldedGroups, current => (current.includes(id) ? current.filter(item => item !== id) : [...current, id])),
    }
    const rowIndex = indexRows(store)

    if (event.surface !== 'terminal') {
      const svgInput = {
        width: columnsToWidth(event.props.bodyColumns),
        columns: event.props.bodyColumns,
        now,
        isFolded: folded,
        range: rangeValue,
        foldedGroups: groups,
        roster: rosterValue,
        rows: rowIndex,
        gauges: gaugeValues,
        isWorking: event.props.isWorking,
        turnStartedAt: startedAt,
        scheme: schemeValue,
      }
      const wait = bandRefreshMs({ rows: rowIndex, roster: rosterValue, range: rangeValue, now, isFolded: folded, isWorking: event.props.isWorking })
      runtime.refreshAt = wait === null ? null : now + wait
      runtime.painters = new Map()
      runtime.requestId = event.requestId
      runtime.isDrawnByTree = true

      return buildDesktopBand({ ui: $.ui.resolve(event), input: svgInput, actions })
    }

    const nextPainters = new Map<string, Painter>()
    const terminalInput = {
      ui,
      columns: event.props.bodyColumns,
      now,
      isFolded: folded,
      range: rangeValue,
      foldedGroups: groups,
      roster: rosterValue,
      rows: rowIndex,
      gauges: gaugeValues,
      isWorking: event.props.isWorking,
      turnStartedAt: startedAt,
      scheme: terminalSchemeOf(schemeValue),
      actions,
    }
    const tree = buildBand(terminalInput, nextPainters)

    const leaveWait = nextLeaveMs(rowIndex.values(), rangeValue, now, folded)
    const quietWait = nextQuietChangeMs(rowIndex.values(), now)
    const waits = [leaveWait, quietWait].filter(wait => wait !== null)
    runtime.refreshAt = waits.length === 0 ? null : now + Math.min(...waits)
    runtime.painters = nextPainters
    runtime.requestId = event.requestId
    runtime.isDrawnByTree = false

    return tree
  })
}
