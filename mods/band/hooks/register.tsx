import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type { AgentState, AgentStore, Gauges, Range, Roster, Scheme } from '../types'

import { EMPTY_GAUGES, isSameGauges, withCache, withCompaction, withUsage } from './gauges'
import {
  DIRECT_GROUP,
  DIRECT_LABEL,
  EMPTY_ROSTER,
  EMPTY_STORE,
  addAgent,
  applyListing,
  isSameRoster,
  moveAgent,
  newAgent,
  rosterOf,
  sessionTotal,
} from './model'
import { TICK_MS, frameAt } from './paint'
import { type Painter, type Rows, buildBand } from './view'

const RECONCILE_MS = 1000

const isFolded = atom({ plugin: 'harness-band', key: 'isFolded' } as const, false)
const range = atom({ plugin: 'harness-band', key: 'range' } as const, '1m')
const foldedGroups = atom({ plugin: 'harness-band', key: 'foldedGroups' } as const, [])
const agents = atom({ plugin: 'harness-band', key: 'agents' } as const, EMPTY_STORE, { shape: 'agents-2' })
const roster = atom({ plugin: 'harness-band', key: 'roster' } as const, EMPTY_ROSTER, { shape: 'roster-1' })
const gauges = atom({ plugin: 'harness-band', key: 'gauges' } as const, EMPTY_GAUGES, { shape: 'gauges-1' })
const turnStartedAt = atom({ plugin: 'harness-band', key: 'turnStartedAt' } as const, null)
const scheme = atom({ plugin: 'harness-band', key: 'scheme' } as const, 'dark')

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

const schemeOf = (value: unknown): Scheme => (typeof value === 'string' && value.includes('light') ? 'light' : 'dark')

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
}

const indexRows = (store: AgentStore | null): Rows => new Map((store?.rows ?? []).map(row => [row.id, row]))

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

const writeGauges = async ($: EngineInterface, next: (current: Gauges) => Gauges): Promise<void> => {
  const current = await read($, gauges)
  const value = next(current)

  if (!isSameGauges(current, value)) {
    await update($, gauges, () => value)
  }
}

const reconcile = async ($: EngineInterface, runtime: Runtime): Promise<void> => {
  if (runtime.isReconciling) {
    return
  }

  runtime.isReconciling = true

  try {
    const list = await $.agent.list()
    await mutateAgents($, runtime, (store, now) => applyListing(store, list, now))
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
    const frame = frameAt(await $.clock.now())
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
  }

  on('session.start', async ($, e, next) => {
    const result = await next(e)
    const usage = await $.session.usage()
    await writeGauges($, current => withUsage(current, usage))
    const rows = await $.config.list()
    await update($, scheme, () => schemeOf(rows.find(row => row.key === 'theme')?.value))
    startClocks($, runtime)

    return result
  })

  on('session.end', ($, e, next) => {
    if (e.reason !== 'clear') {
      stopTimers(runtime)
    }

    return next(e)
  })

  on('config.set', { key: 'theme' }, async ($, e, next) => {
    const result = await next(e)
    const rows = await $.config.list()
    await update($, scheme, () => schemeOf(rows.find(row => row.key === 'theme')?.value))

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
    } else {
      await setAgentState($, runtime, { id: e.agentId, state: 'thinking', command: null })
    }

    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    startClocks($, runtime)
    const id = e.agentId

    if (id === undefined) {
      return next(e)
    }

    await setAgentState($, runtime, { id, state: 'tool', command: describeCall(e) }).catch(cause =>
      reportFailure($, 'tool start', cause),
    )

    try {
      return await next(e)
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
      const usage = e.usage

      if (usage !== undefined) {
        await writeGauges($, current => withCache(current, usage))
      }
    } else {
      await setAgentState($, runtime, { id: e.agentId, state: e.reason === 'answer' ? 'done' : 'failed', command: null })
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
        rows: indexRows(store),
        gauges: gaugeValues,
        isWorking: e.props.isWorking,
        turnStartedAt: startedAt,
        scheme: schemeValue,
        actions: {
          toggleFold: () => void update($, isFolded, current => !current),
          setRange: (chosen: Range) => void update($, range, () => chosen),
          toggleGroup: (id: string) =>
            void update($, foldedGroups, current => (current.includes(id) ? current.filter(item => item !== id) : [...current, id])),
        },
      },
      nextPainters,
    )

    runtime.painters = nextPainters
    runtime.requestId = e.requestId

    return tree
  })
}
