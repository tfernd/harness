import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type { AgentState, AgentStore, Gauges, Range, Roster } from '../types'

import { EMPTY_GAUGES, isSameGauges, withCache, withCompaction, withUsage } from './gauges'
import {
  DIRECT_GROUP,
  DIRECT_LABEL,
  EMPTY_ROSTER,
  EMPTY_STORE,
  type MainActivity,
  addAgent,
  closeOpen,
  lastEventAt,
  applyListing,
  MAIN_ID,
  endBackgroundTask,
  finishAgent,
  startBackgroundTask,
  isSameRoster,
  moveAgent,
  OWNER_QUESTION_TOOLS,
  moveMain,
  nextLeaveMs,
  nextQuietChangeMs,
  newAgent,
  rosterOf,
  sessionTotal,
  terminalSchemeOf,
  themeOf,
} from './model'
import { TICK_MS, frameAt } from './paint'
import { columnsToWidth, refreshAfterMs } from './svg-band'
import { type PieceCache, chooseBand } from './svg-cache'
import { type Actions, type Painter, type Rows, buildBand } from './view'
import { buildDesktopBand } from './view-desktop'

const RECONCILE_MS = 1000

const isFolded = atom({ plugin: 'harness-band', key: 'isFolded' } as const, false, { shape: 'isFolded-2' })
const range = atom({ plugin: 'harness-band', key: 'range' } as const, '1m')
const foldedGroups = atom({ plugin: 'harness-band', key: 'foldedGroups' } as const, [], { shape: 'foldedGroups-2' })
const agents = atom({ plugin: 'harness-band', key: 'agents' } as const, EMPTY_STORE, { shape: 'agents-3' })
const roster = atom({ plugin: 'harness-band', key: 'roster' } as const, EMPTY_ROSTER, { shape: 'roster-1' })
const gauges = atom({ plugin: 'harness-band', key: 'gauges' } as const, EMPTY_GAUGES, { shape: 'gauges-2' })
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
  pieces: ReadonlyMap<string, PieceCache>
  refreshAt: number | null
  retry: Timer | null
  isDrawnByTree: boolean
  isClearing: boolean
  listedIds: Set<string>
}

const indexRows = (store: AgentStore | null): Rows =>
  new Map([...(store?.main ? [store.main] : []), ...(store?.rows ?? [])].map(row => [row.id, row]))

const mutateAgents = async (
  $: EngineInterface,
  runtime: Runtime,
  change: (store: AgentStore, now: number) => AgentStore,
): Promise<void> => {
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

const setAgentState = (
  $: EngineInterface,
  runtime: Runtime,
  change: { id: string; state: AgentState; command: string | null; from?: AgentState },
): Promise<void> => mutateAgents($, runtime, (store, now) => moveAgent(store, { ...change, now }))

const setMainActivity = (
  $: EngineInterface,
  runtime: Runtime,
  change: { activity: MainActivity; from?: AgentState },
): Promise<void> => mutateAgents($, runtime, (store, now) => moveMain(store, { ...change, now }))

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

const noteBackgroundStart = async (
  $: EngineInterface,
  runtime: Runtime,
  input: { owner: string; call: Record<string, unknown>; outcome: unknown },
): Promise<void> => {
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
  } finally {
    runtime.isReconciling = false
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

const scheduleRetry = ($: EngineInterface, runtime: Runtime, retryInMs: number | null): void => {
  runtime.retry?.cancel()
  runtime.retry = null

  if (retryInMs !== null) {
    runtime.retry = $.clock.after(retryInMs, () => $.ui.invalidate('ui.render'))
  }
}

const startClocks = ($: EngineInterface, runtime: Runtime): void => {
  if (runtime.timers.length > 0) {
    return
  }

  runtime.timers.push($.clock.every(TICK_MS, () => void tick($, runtime).catch(cause => reportFailure($, 'tick', cause))))
  runtime.timers.push(
    $.clock.every(RECONCILE_MS, () => void reconcile($, runtime).catch(cause => reportFailure($, 'reconcile', cause))),
  )
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
    pieces: new Map(),
    refreshAt: null,
    retry: null,
    isDrawnByTree: false,
    isClearing: false,
    listedIds: new Set(),
  }

  on('session.start', async ($, e, next) => {
    const result = await next(e)

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

  on('session.end', async ($, e, next) => {
    runtime.isClearing = e.reason === 'clear'

    if (e.reason === 'clear') {
      return next(e)
    }

    stopTimers(runtime)
    runtime.retry?.cancel()
    runtime.retry = null
    await mutateAgents($, runtime, (store, now) => closeOpen(store, now))
    await update($, turnStartedAt, () => null)

    return next(e)
  })

  on('config.set', { key: 'theme' }, async ($, e, next) => {
    const result = await next(e)
    const rows = await $.config.list()
    await update($, scheme, () => themeOf(rows.find(row => row.key === 'theme')?.value))

    return result
  })

  on('agent.spawn', async ($, e, next) => {
    startClocks($, runtime)
    const result = await next(e)

    if (result.agentId !== undefined) {
      const id = result.agentId
      const group = e.workflow === undefined ? DIRECT_GROUP : e.workflow.runId
      const groupLabel = e.workflow === undefined ? DIRECT_LABEL : `workflow ${e.workflow.runId.replace(/^wf_/, '').slice(0, 8)}`

      await mutateAgents($, runtime, (store, now) =>
        addAgent(
          store,
          newAgent({ id, label: `${e.name ?? e.subagentType}-${sessionTotal(store) + 1}`, group, groupLabel, now }),
        ),
      )
    }

    return result
  })

  on('turn.start', async ($, e, next) => {
    startClocks($, runtime)

    if (e.agentId === undefined) {
      const now = await $.clock.now()
      await update($, turnStartedAt, () => now)
      await setMainActivity($, runtime, { activity: { state: 'thinking', command: null } })
    } else {
      await setAgentState($, runtime, { id: e.agentId, state: 'thinking', command: null })
    }

    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    startClocks($, runtime)
    const id = e.agentId
    const stoppedId = stoppedTaskIdOf(e)

    if (stoppedId !== null) {
      const outcome = await next(e)
      await mutateAgents($, runtime, (store, now) => endBackgroundTask(store, { taskId: stoppedId, now })).catch(cause =>
        reportFailure($, 'background stop', cause),
      )

      return outcome
    }

    if (id === undefined) {
      const isQuestion = OWNER_QUESTION_TOOLS.includes(e.tool)
      const started: MainActivity = isQuestion ? { state: 'waiting', command: null } : { state: 'tool', command: describeCall(e) }
      await setMainActivity($, runtime, { activity: started }).catch(cause => reportFailure($, 'main tool start', cause))

      try {
        const outcome = await next(e)
        await noteBackgroundStart($, runtime, { owner: MAIN_ID, call: e, outcome }).catch(cause =>
          reportFailure($, 'main background start', cause),
        )

        return outcome
      } finally {
        for (const from of ['tool', 'waiting'] as const) {
          await setMainActivity($, runtime, { activity: { state: 'thinking', command: null }, from }).catch(cause =>
            reportFailure($, 'main tool end', cause),
          )
        }
      }
    }

    await setAgentState($, runtime, { id, state: 'tool', command: describeCall(e) }).catch(cause =>
      reportFailure($, 'tool start', cause),
    )

    try {
      const outcome = await next(e)
      await noteBackgroundStart($, runtime, { owner: id, call: e, outcome }).catch(cause =>
        reportFailure($, 'background start', cause),
      )

      return outcome
    } finally {
      await setAgentState($, runtime, { id, state: 'thinking', command: null, from: 'tool' }).catch(cause =>
        reportFailure($, 'tool end', cause),
      )
    }
  })

  on('turn.complete', async ($, e, next) => {
    startClocks($, runtime)

    if (e.agentId === undefined) {
      await update($, turnStartedAt, () => null)
      await setMainActivity($, runtime, { activity: null })
      const usage = e.usage

      if (usage !== undefined) {
        const calledAt = await $.clock.now()
        await writeGauges($, current => withCache(current, usage, calledAt))
      }
    } else {
      const agentId = e.agentId
      const state = e.reason === 'answer' ? 'done' : 'failed'
      await mutateAgents($, runtime, (store, now) => finishAgent(store, { id: agentId, state, now }))
    }

    return next(e)
  })

  on('session.append', async ($, e, next) => {
    const taskId = finishedTaskIdOf(e.message.content)

    if (taskId !== null) {
      await mutateAgents($, runtime, (store, now) => endBackgroundTask(store, { taskId, now })).catch(cause =>
        reportFailure($, 'background end', cause),
      )
    }

    return next(e)
  })

  on('session.measure', async ($, e, next) => {
    startClocks($, runtime)
    await writeGauges($, current => withUsage(current, e))

    return next(e)
  })

  on('session.compact', async ($, e, next) => {
    const result = await next(e)

    if (e.trigger !== 'precompute' && result.messages !== undefined && e.agentId === undefined) {
      const tokensBefore = result.tokensBefore
      await writeGauges($, current => withCompaction(current, tokensBefore))
    }

    return result
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) {
      return next(e)
    }

    startClocks($, runtime)
    const ui = $.ui.resolve(e)
    const hasRaster = 'Raster' in ui
    const [folded, rangeValue, groups, rosterValue, gaugeValues, startedAt, schemeValue] = await Promise.all([
      read($, isFolded),
      read($, range),
      read($, foldedGroups),
      read($, roster),
      read($, gauges),
      read($, turnStartedAt),
      read($, scheme),
    ])
    const store = hasRaster ? runtime.store : await read($, agents)
    const now = await $.clock.now()
    const actions: Actions = {
      toggleFold: () => void update($, isFolded, current => !current),
      setRange: (chosen: Range) => void update($, range, () => chosen),
      toggleGroup: (id: string) =>
        void update($, foldedGroups, current => (current.includes(id) ? current.filter(item => item !== id) : [...current, id])),
    }
    const rowIndex = indexRows(store)

    if (e.surface !== 'terminal') {
      const svgInput = {
        width: columnsToWidth(e.props.bodyColumns),
        now,
        isFolded: folded,
        range: rangeValue,
        foldedGroups: groups,
        roster: rosterValue,
        rows: rowIndex,
        gauges: gaugeValues,
        isWorking: e.props.isWorking,
        turnStartedAt: startedAt,
        scheme: schemeValue,
      }
      const choice = chooseBand(runtime.pieces, svgInput)
      const wait = refreshAfterMs(svgInput)
      runtime.pieces = choice.caches
      runtime.refreshAt = wait === null ? null : now + wait
      scheduleRetry($, runtime, choice.retryInMs)
      runtime.painters = new Map()
      runtime.requestId = e.requestId
      runtime.isDrawnByTree = true

      return buildDesktopBand({ ui: $.ui.resolve(e), svgs: choice.svgs, input: svgInput, actions })
    }

    const nextPainters = new Map<string, Painter>()
    const tree = buildBand(
      {
        ui,
        columns: e.props.bodyColumns,
        now,
        isFolded: folded,
        range: rangeValue,
        foldedGroups: groups,
        roster: rosterValue,
        rows: rowIndex,
        gauges: gaugeValues,
        isWorking: e.props.isWorking,
        turnStartedAt: startedAt,
        scheme: terminalSchemeOf(schemeValue),
        actions,
      },
      nextPainters,
    )

    const leaveWait = nextLeaveMs(rowIndex.values(), rangeValue, now, folded)
    const quietWait = nextQuietChangeMs(rowIndex.values(), now)
    const waits = [leaveWait, quietWait].filter(wait => wait !== null)
    runtime.refreshAt = waits.length === 0 ? null : now + Math.min(...waits)
    runtime.painters = nextPainters
    runtime.requestId = e.requestId
    runtime.isDrawnByTree = false

    return tree
  })
}
