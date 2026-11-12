import type { Elements, RenderElement } from 'claude-code'

import type { Gauges, NamedLimit, Range } from '../types'

import { type C1Palette, type Tone, paletteOf } from './c1-theme'
import { BAR_HEIGHT, FULL_BAR_WIDTH, MINI_BAR_WIDTH, barSvg, miniLanesSvg } from './c1-svg'
import { type AxisTick, type LaneRow, MINI_LANES_RANGE, TIMELINE_RANGES, axisTicksOf, isLongSession, lanesOf, longSessionText, miniLanesOf, resetTextOf, shortLimitName, spendOf, timelineWindowOf, toneOfPercent } from './c1'
import { formatUsd } from './cost'
import { formatClock, formatTokens } from './format'
import { countAgents, windowFor } from './layout'
import type { SvgInput } from './svg-band'
import { bandColorsOf } from './svg-theme'
import type { Actions } from './view'

export type SvgTable = Elements['desktop'] | Elements['vscode'] | Elements['mobile']

export type DesktopView = {
  ui: SvgTable
  input: SvgInput
  actions: Actions
}

export const GLYPH_COLUMNS = 11
export const NAME_COLUMNS = 22
export const BADGE_COLUMNS = 8
export const TIME_COLUMNS = 7
export const TOKENS_COLUMNS = 13
export const COST_COLUMNS = 9
export const TRACK_MIN_COLUMNS = 24
export const BLOCK_COLUMNS = 24
export const MAIN_LEGEND = 'main session'
export const AGENTS_LEGEND = 'agents'

const FRAME_PAD_X = 'sm'
const SECTION_GAP = 'md'
const ITEM_GAP = 'xs'

const colorOf = (palette: C1Palette, tone: Tone): string => palette[tone]

const rangeLabelOf = (range: Range): string => range

export const buildDesktopBand = (view: DesktopView): RenderElement => {
  const { Box, Text, Button, Svg } = view.ui
  const { input, actions } = view
  const { isFolded, gauges, now } = input
  const palette = paletteOf(input.scheme)
  const colors = bandColorsOf(input.scheme)
  const surface = colors.surface === undefined ? {} : { backgroundColor: colors.surface }
  const counts = countAgents(input.roster.rows, { done: input.roster.evictedDone, failed: input.roster.evictedFailed })
  const window = timelineWindowOf({ range: input.range, now, sessionStartedAt: gauges.sessionStartedAt, rows: input.rows.values() })
  const lanes = lanesOf({ roster: input.roster, rows: input.rows, now, window, sessionStartedAt: gauges.sessionStartedAt })
  const spend = spendOf({ gauges, rows: input.rows, now })

  const bar = (key: string, percent: number, width: number, alt: string) => {
    const svg = barSvg({ percent, tone: toneOfPercent(percent), width, setting: input.scheme })

    return <Svg key={key} source={svg.source} alt={alt} width={svg.width} height={svg.height} />
  }

  const countsBox = (
    <Box key="counts" flexDirection="row" gap={SECTION_GAP} alignItems="center" flexShrink={0}>
      <Text bold dimColor={counts.live === 0} color={palette.run}>{'▶ ' + counts.live}</Text>
      <Text bold dimColor={counts.done === 0} color={palette.done}>{'✓ ' + counts.done}</Text>
      <Text bold dimColor={counts.failed === 0} color={palette.fail}>{'✕ ' + counts.failed}</Text>
    </Box>
  )

  const costBox =
    gauges.costUsd === null ? null : (
      <Box key="cost" flexDirection="row" gap={ITEM_GAP} alignItems="center" flexShrink={0}>
        <Text bold>{formatUsd(gauges.costUsd)}</Text>
        {isFolded ? null : <Text dimColor>session</Text>}
      </Box>
    )

  const foldButton = (
    <Button key="fold" plain onPress={() => actions.toggleFold()}>
      {isFolded ? '▾' : '▴'}
    </Button>
  )

  const contextText = (gaugeValues: Gauges) => {
    if (gaugeValues.contextPercent === null) {
      return null
    }

    const tone = toneOfPercent(gaugeValues.contextPercent)

    return (
      <Box key="ctx" flexDirection="row" alignItems="center" flexShrink={0}>
        <Text dimColor>{'ctx '}</Text>
        <Text bold color={tone === 'ink' ? undefined : colorOf(palette, tone)}>{Math.round(gaugeValues.contextPercent) + '%'}</Text>
        {isLongSession(gaugeValues) ? <Text color={palette.warn}>{' ▲'}</Text> : null}
      </Box>
    )
  }

  const miniLimit = (limit: NamedLimit) => (
    <Box key={'mini-' + limit.kind} flexDirection="row" gap={ITEM_GAP} alignItems="center" flexShrink={0}>
      <Text dimColor>{shortLimitName(limit)}</Text>
      {bar('mini-bar-' + limit.kind, limit.percent, MINI_BAR_WIDTH, shortLimitName(limit) + ' ' + Math.round(limit.percent) + '%')}
      <Text bold>{Math.round(limit.percent) + '%'}</Text>
    </Box>
  )

  if (isFolded) {
    const miniWindow = windowFor(MINI_LANES_RANGE, now, now)
    const miniRows = miniLanesOf({ roster: input.roster, rows: input.rows, window: miniWindow })
    const mini = miniRows.length === 0 ? null : miniLanesSvg({ lanes: miniRows, window: miniWindow, setting: input.scheme })

    return (
      <Box flexDirection="row" alignItems="center" gap={SECTION_GAP} paddingX={FRAME_PAD_X} {...surface}>
        {countsBox}
        {mini === null ? null : (
          <Box key="mini-lanes" alignSelf="center" flexShrink={1} minWidth={0} overflow="hidden">
            <Svg source={mini.source} alt={'agent lanes, last 5m'} width={mini.width} height={mini.height} />
          </Box>
        )}
        {costBox}
        {contextText(gauges)}
        {gauges.limits.length === 0 ? null : (
          <Box key="mini-limits" flexDirection="row" gap={SECTION_GAP} alignItems="center" flexShrink={0}>
            {gauges.limits.map(miniLimit)}
          </Box>
        )}
        <Box key="spacer" flexGrow={1} />
        {foldButton}
      </Box>
    )
  }

  const block = (spec: { key: string; title: string; value: string; percent: number | null; note: string }) => (
    <Box key={spec.key} flexDirection="column" width={BLOCK_COLUMNS} flexShrink={0}>
      <Box flexDirection="row" justifyContent="space-between">
        <Text bold wrap="truncate-end">{spec.title}</Text>
        <Text bold wrap="truncate-end">{spec.value}</Text>
      </Box>
      {spec.percent === null ? null : bar(spec.key + '-bar', spec.percent, FULL_BAR_WIDTH, spec.title + ' ' + spec.value)}
      <Text dimColor wrap="truncate-end">{spec.note}</Text>
    </Box>
  )

  const limitBlock = (limit: NamedLimit) => block({ key: 'limit-' + limit.kind, title: limit.name, value: Math.round(limit.percent) + '%', percent: limit.percent, note: resetTextOf(limit, now) })

  const contextBlock =
    gauges.contextPercent === null
      ? []
      : [block({ key: 'limit-context', title: 'Context', value: Math.round(gauges.contextPercent) + '%', percent: gauges.contextPercent, note: gauges.contextTokens !== null && gauges.contextWindow !== null ? formatTokens(gauges.contextTokens) + ' of ' + formatTokens(gauges.contextWindow) + ' tokens' : '' })]

  const sessionBlocks = [
    block({ key: 'spend-session', title: 'Session cost', value: spend.sessionUsd === null ? '—' : formatUsd(spend.sessionUsd), percent: null, note: spend.pricedAgents === 0 ? 'agents: no estimate' : 'agents ~' + formatUsd(spend.agentsUsd) + ', estimated' }),
    block({ key: 'spend-tokens', title: 'Tokens in / out', value: formatTokens(spend.tokensIn) + ' / ' + formatTokens(spend.tokensOut), percent: null, note: 'main chat and agents' }),
    block({ key: 'spend-turns', title: 'Turns · elapsed', value: spend.turns + ' · ' + (spend.elapsedMs === null ? '—' : formatClock(spend.elapsedMs)), percent: null, note: '' }),
  ]

  const blocks = gauges.limits.length > 0 ? [...gauges.limits.map(limitBlock), ...contextBlock] : [...sessionBlocks, ...contextBlock]

  const limitBlocks = (
    <Box key="limit-blocks" flexDirection="row" flexWrap="wrap" columnGap={SECTION_GAP} rowGap={ITEM_GAP} paddingX={FRAME_PAD_X} paddingY={ITEM_GAP}>
      {blocks}
    </Box>
  )

  const note =
    isLongSession(gauges) && !input.isNoteDismissed ? (
      <Box key="long-session" flexDirection="row" alignItems="center" gap={SECTION_GAP} paddingX={FRAME_PAD_X} backgroundColor={palette.noteBackground}>
        <Box flexGrow={1} flexShrink={1}>
          <Text color={palette.warn} wrap="wrap">{'▲ ' + longSessionText(gauges)}</Text>
        </Box>
        <Button key="dismiss-note" role="dismiss" onPress={() => actions.dismissNote()}>
          Dismiss
        </Button>
      </Box>
    ) : null

  const rangeButtons = (
    <Box key="ranges" flexDirection="row" gap={ITEM_GAP} flexShrink={0}>
      {TIMELINE_RANGES.map(name => (
        <Button key={'range-' + name} variant={name === input.range ? 'primary' : 'secondary'} onPress={() => actions.setRange(name)}>
          {rangeLabelOf(name)}
        </Button>
      ))}
    </Box>
  )

  const legend = (
    <Box key="legend" flexDirection="row" alignItems="center" gap={SECTION_GAP} paddingX={FRAME_PAD_X}>
      <Text bold color={palette.ink}>{'● ' + MAIN_LEGEND}</Text>
      <Text bold color={palette.run}>{'● ' + AGENTS_LEGEND}</Text>
      <Box flexGrow={1} />
      {rangeButtons}
    </Box>
  )

  const cell = (key: string, columns: number, text: string, isStrong = false) => (
    <Box key={key} width={columns} flexShrink={0} justifyContent="flex-end">
      <Text bold={isStrong} dimColor={!isStrong} wrap="truncate-end">{text}</Text>
    </Box>
  )

  const axis = (ticks: readonly AxisTick[]) => (
    <Box key="axis" flexDirection="row" alignItems="center" gap={ITEM_GAP} paddingX={FRAME_PAD_X}>
      <Box width={GLYPH_COLUMNS + NAME_COLUMNS + BADGE_COLUMNS} flexShrink={0}>
        <Text dimColor>Agent</Text>
      </Box>
      <Box flexGrow={1} flexShrink={1} minWidth={TRACK_MIN_COLUMNS} flexDirection="row" justifyContent="space-between">
        {ticks.map(tick => (
          <Text key={'tick-' + tick.fraction} dimColor>
            {tick.text}
          </Text>
        ))}
      </Box>
      {cell('head-time', TIME_COLUMNS, 'Time')}
      {cell('head-tokens', TOKENS_COLUMNS, 'In / out')}
      {cell('head-cost', COST_COLUMNS, 'Cost')}
    </Box>
  )

  const track = (row: LaneRow) => (
    <Box key={'track-' + row.id} flexGrow={1} flexShrink={1} minWidth={TRACK_MIN_COLUMNS} flexDirection="row" overflow="hidden" backgroundColor={palette.rail}>
      {row.span === null ? null : <Box key="lead" width={row.span.left + '%'} flexShrink={0} />}
      {row.span === null ? null : (
        <Box key="fill" width={row.span.width + '%'} flexShrink={0} overflow="hidden" backgroundColor={colorOf(palette, row.tone)}>
          <Text bold color={palette.onFill} wrap="truncate-end">{row.inside}</Text>
        </Box>
      )}
      {row.reason === null ? null : (
        <Text bold color={palette.fail} wrap="truncate-end">{' ' + row.reason}</Text>
      )}
      <Box key="now" position="absolute" right={0} top={0} width={1} height={1} backgroundColor={palette.ink} />
    </Box>
  )

  const nameCell = (row: LaneRow) => (
    <Box key={'name-' + row.id} width={NAME_COLUMNS} flexShrink={0} flexDirection="row" gap={ITEM_GAP} overflow="hidden">
      <Text bold wrap="truncate-end">{row.label}</Text>
      {row.type === null || row.label.startsWith(row.type) ? null : <Text dimColor wrap="truncate-end">{row.type}</Text>}
    </Box>
  )

  const laneRow = (row: LaneRow) => (
    <Box key={'lane-' + row.id} flexDirection="row" alignItems="center" gap={ITEM_GAP} paddingX={FRAME_PAD_X}>
      <Box key={'glyph-' + row.id} width={GLYPH_COLUMNS} flexShrink={0}>
        <Text bold color={colorOf(palette, row.tone)} wrap="truncate-end">{row.glyph + ' ' + row.word}</Text>
      </Box>
      {nameCell(row)}
      <Box key={'badge-' + row.id} width={BADGE_COLUMNS} flexShrink={0}>
        {row.model === null ? null : <Text dimColor wrap="truncate-end">{row.model}</Text>}
      </Box>
      {track(row)}
      {cell('time-' + row.id, TIME_COLUMNS, row.time, true)}
      {cell('tokens-' + row.id, TOKENS_COLUMNS, row.tokens)}
      {cell('cost-' + row.id, COST_COLUMNS, row.cost)}
    </Box>
  )

  const remainder = (key: string, text: string) => (
    <Box key={key} paddingX={FRAME_PAD_X}>
      <Text dimColor>{text}</Text>
    </Box>
  )

  const timeline = (
    <Box key="timeline" flexDirection="column" rowGap={ITEM_GAP} paddingBottom={ITEM_GAP}>
      {legend}
      {axis(axisTicksOf(window))}
      {laneRow(lanes.main)}
      {lanes.agents.length === 0 ? remainder('no-agents', 'No agents yet.') : lanes.agents.map(laneRow)}
      {lanes.earlier === 0 ? null : remainder('earlier', '+' + lanes.earlier + ' earlier')}
      {lanes.hidden === 0 ? null : remainder('hidden', '+' + lanes.hidden + ' more agents not drawn')}
    </Box>
  )

  return (
    <Box flexDirection="column" paddingBottom={ITEM_GAP} {...surface}>
      <Box key="controls" flexDirection="row" alignItems="center" gap={SECTION_GAP} paddingX={FRAME_PAD_X}>
        {countsBox}
        {costBox}
        <Box key="spacer" flexGrow={1} />
        {foldButton}
      </Box>
      {limitBlocks}
      {note}
      {timeline}
    </Box>
  )
}
