import type { Color, Elements, RenderElement } from 'claude-code'

import type { AgentRow, AgentState, Gauges, Phase, Range, Roster, Scheme } from '../types'

import { type BandPartName, FOLDED_RANGE, RANGES, countAgents, earliestStart, groupAgents, splitByWindow, tracedRows, layoutBand, partWidth, windowFor } from './layout'
import { STATE_ICON, MAIN_ID, MAIN_LABEL, MAIN_STATE_WORD, stateWordOf } from './model'
import { barText, formatClock, formatReset, formatShort, formatTokens } from './format'
import { type Frame, type Grid, type Palette, type TextAlign, type TextSpan, PALETTES, encodeGrid, frameAt, hexOf, laneColors, paintLanes, paintTextRows, paintTraces, runsOf } from './paint'

export type Table = Elements['terminal'] | Elements['desktop'] | Elements['vscode'] | Elements['mobile']

export type Rows = ReadonlyMap<string, AgentRow>

export type Painter = { paint: (frame: Frame, rows: Rows) => string; last: string }

export type Actions = {
  toggleFold: () => void
  setRange: (range: Range) => void
  toggleGroup: (id: string) => void
}

export type ViewInput = {
  ui: Table
  columns: number
  now: number
  isFolded: boolean
  range: Range
  foldedGroups: readonly string[]
  roster: Roster
  rows: Rows
  gauges: Gauges
  isWorking: boolean
  turnStartedAt: number | null
  scheme: Scheme
  actions: Actions
}

const MAX_CARDS = 3
const MAX_TRACE_AGENTS = 8
const GAUGE_BAR_WIDTH = 9
export const CLOCK_COLUMNS = 'turn 99:59:59'.length
const STATUS_COLUMNS = 7
const RESET_COLUMNS = ' in 23h59'.length
const ELAPSED_COLUMNS = 5
const MIN_CARD_COLUMNS = 16
const MIN_TRACK_COLUMNS = 8
const STATE_COLUMNS = 10
const WIDE_COLUMNS = 60
const TRACE_LABEL_COLUMNS = 9
const BORDER_COLUMNS = 2

const PHASE_ICON: Record<Phase, string> = { live: '●', done: '✓', failed: '✕' }

const PHASE_THEME: Record<Phase, Color> = { live: 'success', done: 'subtle', failed: 'error' }

const idleCommand = (agent: AgentRow): string => {
  if (agent.command !== null) {
    return agent.command
  }

  return agent.state === 'launched' ? 'starting...' : agent.state === 'waiting' ? 'waiting...' : 'thinking...'
}

const levelColor = (percent: number): Color => (percent >= 90 ? 'error' : percent >= 70 ? 'warning' : 'success')

type TextBlock = { key: string; columns: number; rowCount: number; align: TextAlign }

const statusOf = (input: { isWorking: boolean; rows: Rows }): 'WORKING' | 'WAITING' | 'IDLE' => {
  if (input.isWorking) {
    return 'WORKING'
  }

  return [...input.rows.values()].some(row => row.state === 'waiting') ? 'WAITING' : 'IDLE'
}

export const buildBand = (input: ViewInput, painters: Map<string, Painter>): RenderElement => {
  const { Box, Text, Button } = input.ui
  const Raster = 'Raster' in input.ui ? input.ui.Raster : null
  const palette: Palette = PALETTES[input.scheme]
  const startFrame = frameAt(input.now)
  const counts = countAgents(input.roster.rows, { done: input.roster.evictedDone, failed: input.roster.evictedFailed })
  const liveRoster = tracedRows(input.roster.rows, input.rows, input.now)
  const innerColumns = Math.max(1, input.columns - BORDER_COLUMNS)
  const sessionStart = input.gauges.sessionStartedAt ?? input.now

  const mount = (key: string, paintGrid: (frame: Frame, rows: Rows) => Grid): string => {
    const paint = (frame: Frame, rows: Rows): string => encodeGrid(paintGrid(frame, rows))
    const cells = paint(startFrame, input.rows)
    painters.set(key, { paint, last: cells })

    return cells
  }

  const textBlock = (block: TextBlock, read: (frame: Frame, rows: Rows) => TextSpan[]) => {
    if (Raster === null) {
      return (
        <Box key={block.key} flexDirection="column">
          {read(startFrame, input.rows).map(span => (
            <Text color={span.color === null ? undefined : hexOf(span.color)} dimColor={span.color === null} wrap="truncate-end">
              {span.text.trim()}
            </Text>
          ))}
        </Box>
      )
    }

    const cells = mount(block.key, (frame, rows) => paintTextRows(read(frame, rows), block.columns, block.align))

    return <Raster key={block.key} columns={block.columns} rows={block.rowCount} cells={cells} />
  }

  const windowAt = (range: Range, frame: Frame, rows: Rows) => windowFor(range, frame.now, earliestStart([...rows.values()], sessionStart))

  const membersOf = (ids: readonly string[], rows: Rows): (AgentRow | undefined)[] => ids.map(id => rows.get(id))

  const lanes = (key: string, ids: readonly string[], columns: number, range: Range, isTrace: boolean) => {
    if (Raster === null) {
      return (
        <Box flexDirection="column">
          {membersOf(ids, input.rows).map((agent, index) => (
            <Box key={`${key}-${ids[index]}`} flexDirection="row">
              {agent === undefined ? null : laneRuns(agent, columns, range, startFrame)}
            </Box>
          ))}
        </Box>
      )
    }

    const paintGrid = (frame: Frame, rows: Rows): Grid => {
      const options = { columns, window: windowAt(range, frame, rows), palette, frame }
      const members = membersOf(ids, rows)

      return isTrace ? paintTraces(members, options) : paintLanes(members, options)
    }
    const rowCount = isTrace ? Math.max(1, Math.ceil(ids.length / 2)) : Math.max(1, ids.length)
    const cells = mount(key, paintGrid)

    return <Raster key={key} columns={columns} rows={rowCount} cells={cells} />
  }

  const laneRuns = (agent: AgentRow, columns: number, range: Range, frame: Frame) => {
    const colors = laneColors(agent, windowAt(range, frame, input.rows), columns, palette, frame)

    return runsOf(colors).map(run => <Text color={hexOf(run.color)}>{'█'.repeat(run.length)}</Text>)
  }

  const gauge = (name: BandPartName, label: string, percent: number, detail: RenderElement | null, hasDetail: boolean, color: Color) => (
    <Box key={name} flexDirection="column" width={partWidth(name, hasDetail)} paddingRight={1}>
      <Box flexDirection="row">
        <Text bold color={color}>
          {`${label} ${Math.round(percent)}%`}
        </Text>
        {detail}
      </Box>
      <Text color={color}>{barText(percent, GAUGE_BAR_WIDTH)}</Text>
    </Box>
  )

  const resetCell = (name: BandPartName, resetsAt: number | null, hasDetail: boolean) => (!hasDetail || resetsAt === null ? null : textBlock({ key: `reset-${name}`, columns: RESET_COLUMNS, rowCount: 1, align: 'left' }, frame => [{ text: ` in ${formatReset(resetsAt - frame.now)}`, color: null }]))

  const present: BandPartName[] = ['status']
  const { gauges } = input

  if (gauges.contextPercent !== null) present.push('context')
  if (gauges.cachePercent !== null) present.push('cache')
  if (gauges.fiveHour !== null) present.push('fiveHour')
  if (gauges.sevenDay !== null) present.push('sevenDay')
  present.push('counts', 'toggle')

  const bandLayout = layoutBand(innerColumns, present)

  const statusColor = (word: string): number => (word === 'WORKING' ? palette.thinking : word === 'WAITING' ? palette.waiting : palette.launched)

  const partFor = (name: BandPartName, hasDetail: boolean) => {
    if (name === 'status') {
      return (
        <Box key="status" flexDirection="column" width={partWidth('status', hasDetail)} paddingRight={1}>
          {textBlock({ key: 'status-word', columns: STATUS_COLUMNS, rowCount: 1, align: 'left' }, (_, rows) => {
            const word = statusOf({ isWorking: input.isWorking, rows })

            return [{ text: word, color: statusColor(word) }]
          })}
          {textBlock({ key: 'clock', columns: CLOCK_COLUMNS, rowCount: 1, align: 'left' }, frame => [
            {
              text: input.isWorking && input.turnStartedAt !== null ? `turn ${formatClock(frame.now - input.turnStartedAt)}` : '',
              color: null,
            },
          ])}
        </Box>
      )
    }

    if (name === 'context' && gauges.contextPercent !== null) {
      const used = gauges.contextTokens !== null && gauges.contextWindow !== null ? `${formatTokens(gauges.contextTokens)}/${formatTokens(gauges.contextWindow)}` : ''
      const from = gauges.compactedFrom !== null ? ` ↻${formatTokens(gauges.compactedFrom)}` : ''
      const detail = hasDetail && `${used}${from}` !== '' ? <Text dimColor>{` ${used}${from}`}</Text> : null

      return gauge(name, 'ctx', gauges.contextPercent, detail, hasDetail, levelColor(gauges.contextPercent))
    }

    if (name === 'cache' && gauges.cachePercent !== null) {
      return gauge(name, 'cache', gauges.cachePercent, null, hasDetail, gauges.cachePercent >= 70 ? 'success' : 'warning')
    }

    if (name === 'fiveHour' && gauges.fiveHour !== null) {
      return gauge(name, '5h', gauges.fiveHour.percent, resetCell(name, gauges.fiveHour.resetsAt, hasDetail), hasDetail, levelColor(gauges.fiveHour.percent))
    }

    if (name === 'sevenDay' && gauges.sevenDay !== null) {
      return gauge(name, 'wk', gauges.sevenDay.percent, resetCell(name, gauges.sevenDay.resetsAt, hasDetail), hasDetail, levelColor(gauges.sevenDay.percent))
    }

    if (name === 'counts') {
      return (
        <Box key="counts" flexDirection="column" width={partWidth('counts', hasDetail)}>
          <Text bold color="success">{`● ${counts.live} live`}</Text>
          <Box flexDirection="row" gap={1}>
            <Text dimColor>{`✓${counts.done}`}</Text>
            <Text color={counts.failed > 0 ? 'error' : undefined} dimColor={counts.failed === 0}>{`✕${counts.failed}`}</Text>
            <Text dimColor>{`Σ${counts.total}`}</Text>
          </Box>
        </Box>
      )
    }

    if (name === 'toggle') {
      return (
        <Box key="toggle" width={partWidth('toggle', hasDetail)}>
          <Button key="fold" onPress={() => input.actions.toggleFold()}>
            {input.isFolded ? '▾' : '▴'}
          </Button>
        </Box>
      )
    }

    return null
  }

  const bandRow = (
    <Box key="band" flexDirection="row">
      {bandLayout.parts.map(name => partFor(name, bandLayout.hasDetail))}
    </Box>
  )

  const traces = () => {
    const shown = liveRoster.slice(0, MAX_TRACE_AGENTS)

    if (shown.length === 0) {
      return null
    }

    const columns = Math.max(MIN_TRACK_COLUMNS, innerColumns - TRACE_LABEL_COLUMNS - 1)
    const hidden = liveRoster.length - shown.length
    const shownIds = shown.map(row => row.id)

    return (
      <Box key="traces" flexDirection="row" gap={1}>
        <Text dimColor>{hidden > 0 ? `live +${hidden}` : 'live 1m'}</Text>
        {lanes('traces', shownIds, columns, FOLDED_RANGE, true)}
      </Box>
    )
  }

  const cards = () => {
    if (liveRoster.length === 0) {
      return null
    }

    const cardCount = Math.max(1, Math.min(MAX_CARDS, Math.floor(innerColumns / MIN_CARD_COLUMNS)))
    const shown = liveRoster.slice(0, cardCount)
    const hidden = liveRoster.length - shown.length
    const plusColumns = hidden > 0 ? 6 : 0
    const width = Math.floor((innerColumns - plusColumns) / shown.length)
    const lineColumns = Math.max(1, width - BORDER_COLUMNS - 2)

    return (
      <Box key="cards" flexDirection="row">
        {shown.map(agent => (
          <Box key={`card-${agent.id}`} flexDirection="column" borderStyle="round" borderColor="inactive" width={width} paddingX={1}>
            <Box flexDirection="row" justifyContent="space-between">
              <Text bold wrap="truncate-end">
                {agent.label}
              </Text>
              {textBlock({ key: `elapsed-${agent.id}`, columns: ELAPSED_COLUMNS, rowCount: 1, align: 'right' }, (frame, rows) => {
                const row = rows.get(agent.id)

                return [{ text: row === undefined ? '' : formatShort(frame.now - row.startedAt), color: null }]
              })}
            </Box>
            {textBlock({ key: `line-${agent.id}`, columns: lineColumns, rowCount: 1, align: 'left' }, (_, rows) => {
              const row = rows.get(agent.id)

              return [row === undefined ? { text: '', color: null } : { text: `${STATE_ICON[row.state]} ${idleCommand(row)}`, color: palette[row.state] }]
            })}
          </Box>
        ))}
        {hidden > 0 ? <Text dimColor>{` +${hidden}`}</Text> : null}
      </Box>
    )
  }

  const rangeRow = (
    <Box key="ranges" flexDirection="row" gap={1}>
      <Text dimColor>range</Text>
      {RANGES.map(name => (
        <Button key={`range-${name}`} variant={name === input.range ? 'primary' : 'secondary'} onPress={() => input.actions.setRange(name)}>
          {name}
        </Button>
      ))}
    </Box>
  )

  const mainRow = () => {
    const stateColumns = innerColumns >= WIDE_COLUMNS ? STATE_COLUMNS : 0
    const labelColumns = Math.max(10, Math.min(20, Math.floor(innerColumns * 0.22)))
    const trackColumns = Math.max(MIN_TRACK_COLUMNS, innerColumns - labelColumns - stateColumns - 2)

    return (
      <Box key="main-row" flexDirection="row" gap={1}>
        <Box width={labelColumns}>
          <Text color="success" wrap="truncate-end">
            {`● ${MAIN_LABEL}`}
          </Text>
        </Box>
        {lanes('lanes-main', [MAIN_ID], trackColumns, input.range, false)}
        {stateColumns > 0
          ? textBlock({ key: 'states-main', columns: stateColumns, rowCount: 1, align: 'left' }, (frame, rows) => {
              const row = rows.get(MAIN_ID)

              return [{ text: row === undefined ? MAIN_STATE_WORD.launched : stateWordOf(row, frame.now), color: palette[row?.state ?? 'launched'] }]
            })
          : null}
      </Box>
    )
  }

  const timeline = () => {
    const stateColumns = innerColumns >= WIDE_COLUMNS ? STATE_COLUMNS : 0
    const labelColumns = Math.max(10, Math.min(20, Math.floor(innerColumns * 0.22)))
    const trackColumns = Math.max(MIN_TRACK_COLUMNS, innerColumns - labelColumns - stateColumns - 2)
    const scale = input.range === 'session' ? 'session' : input.range
    const windowStartOf = windowFor(input.range, input.now, earliestStart([...input.rows.values()], sessionStart)).start

    return (
      <Box key="timeline" flexDirection="column">
        {rangeRow}
        <Box flexDirection="row" gap={1}>
          <Box width={labelColumns}>
            <Text dimColor>AGENT</Text>
          </Box>
          <Box width={trackColumns} flexDirection="row" justifyContent="space-between">
            <Text dimColor>{`-${scale}`}</Text>
            <Text dimColor>now</Text>
          </Box>
          {stateColumns > 0 ? <Text dimColor>STATE</Text> : null}
        </Box>
        {mainRow()}
        {groupAgents(input.roster.rows).map(group => {
          const isFolded = input.foldedGroups.includes(group.id)
          const title = `${isFolded ? '▸' : '▾'} ${group.label} · ${group.counts.live} live · ${group.counts.done + group.counts.failed} ended`
          const { shown, earlier } = splitByWindow(group.agents, input.rows, windowStartOf)
          const ids = shown.map(agent => agent.id)

          if (shown.length === 0 && earlier === 0) {
            return null
          }

          return (
            <Box key={`group-${group.id}`} flexDirection="column">
              <Button key={`group-button-${group.id}`} plain onPress={() => input.actions.toggleGroup(group.id)}>
                {title}
              </Button>
              {isFolded ? null : (
                <Box flexDirection="row" gap={1}>
                  <Box flexDirection="column" width={labelColumns}>
                    {shown.map(agent => (
                      <Text color={PHASE_THEME[agent.phase]} wrap="truncate-end">
                        {`${PHASE_ICON[agent.phase]} ${agent.label}`}
                      </Text>
                    ))}
                  </Box>
                  {lanes(`lanes-${group.id}`, ids, trackColumns, input.range, false)}
                  {stateColumns > 0
                    ? textBlock({ key: `states-${group.id}`, columns: stateColumns, rowCount: Math.max(1, ids.length), align: 'left' }, (frame, rows) =>
                        ids.map(id => {
                          const row = rows.get(id)

                          return row === undefined ? { text: '', color: null } : { text: stateWordOf(row, frame.now), color: palette[row.state] }
                        }),
                      )
                    : null}
                </Box>
              )}
              {isFolded || earlier === 0 ? null : <Text dimColor>{`+${earlier} earlier`}</Text>}
            </Box>
          )
        })}
      </Box>
    )
  }

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="promptBorder">
      {bandRow}
      {input.isFolded ? traces() : cards()}
      {input.isFolded ? null : timeline()}
    </Box>
  )
}
