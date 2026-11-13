import type { Elements, RenderElement } from 'claude-code'

import type { Range } from '../types'

import { type Activity, cellsOf } from './activity'
import { type Arc, apiBillingText, arcsOf, isWarning, legendColumnsOf, percentTextOf, resetClockOf, toneOfPercent } from './arcs'
import { COST_COLUMNS, GUTTER_COLUMNS, MAIN_COLUMN_PADDING_COLUMNS, SECTION_GAP_COLUMNS, STRIP_MIN_COLUMNS, TILE_PADDING_COLUMNS, TIME_COLUMNS, TOKENS_COLUMNS, legendColumnsWidthOf, miniLaneColumnsOf, pixelsOf, stripColumnsOf } from './desktop-fit'
import { type DesktopPalette, type Tone, arcColorOf, paletteOf } from './desktop-theme'
import { GUTTER_BAR_WIDTH, MINI_LANE_CELLS, STRIP_HEIGHT, barSvg, miniLanesSvg, ringSvg, ruleSvg, stripSvg } from './desktop-svg'
import { type Ghost, type Tile, MINI_LANES_RANGE, TIMELINE_RANGES, mainEstimateLabelOf, miniLaneRowsOf, rangeLabelOf, spendOf, tilesOf, timelineWindowOf } from './desktop'
import { formatUsd } from './cost'
import { formatTokens } from './format'
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

export const AGENTS_LABEL = 'agents'
export const MAIN_NAME = 'main'
export const TILE_MIN_COLUMNS = TILE_PADDING_COLUMNS + STRIP_MIN_COLUMNS + TIME_COLUMNS + TOKENS_COLUMNS + COST_COLUMNS + 3 * SECTION_GAP_COLUMNS
export { COST_COLUMNS, GUTTER_COLUMNS, MAIN_COLUMN_PADDING_COLUMNS, SECTION_GAP_COLUMNS, STRIP_MIN_COLUMNS, TILE_PADDING_COLUMNS, TIME_COLUMNS, TOKENS_COLUMNS }

export const TWO_TILES_MIN_COLUMNS = GUTTER_COLUMNS + 1 + MAIN_COLUMN_PADDING_COLUMNS + 2 * TILE_MIN_COLUMNS + 1

const FRAME_PAD_X = 'sm'
const SECTION_GAP = 'md'
const ITEM_GAP = 'xs'

const colorOfTone = (palette: DesktopPalette, tone: Tone): string => (tone === 'idle' ? palette.muted : palette[tone])

const toneColorOfPercent = (palette: DesktopPalette, percent: number): string | undefined => {
  const tone = toneOfPercent(percent)

  return tone === 'ink' ? undefined : colorOfTone(palette, tone)
}

const groupsOf = <Item,>(items: readonly Item[], size: number): Item[][] => Array.from({ length: Math.ceil(items.length / size) }, (_, index) => items.slice(index * size, index * size + size))

export const buildDesktopBand = (view: DesktopView): RenderElement => {
  const { Box, Text, Button, Svg } = view.ui
  const { input, actions } = view
  const { isFolded, gauges, now } = input
  const palette = paletteOf(input.scheme)
  const colors = bandColorsOf(input.scheme)
  const surface = colors.surface === undefined ? {} : { backgroundColor: colors.surface }
  const counts = countAgents(input.roster.rows, { done: input.roster.evictedDone, failed: input.roster.evictedFailed })
  const arcs = arcsOf(gauges)
  const window = timelineWindowOf({ range: input.range, now, sessionStartedAt: gauges.sessionStartedAt, rows: input.rows.values() })
  const tiles = tilesOf({ roster: input.roster, rows: input.rows, now, window, gauges })
  const spend = spendOf({ gauges, rows: input.rows })
  const hasLimits = gauges.limits.length > 0
  const hasAnswerSinceLoad = gauges.lastCallAt !== null && gauges.lastCallAt >= input.loadedAt
  const isApiBilling = !hasLimits && hasAnswerSinceLoad
  const apiText = isApiBilling ? apiBillingText(spend.tokensIn, spend.tokensOut) : null
  const hasAgents = input.roster.rows.length + input.roster.evictedDone + input.roster.evictedFailed > 0
  const hasAgentSpend = hasAgents && spend.agentsUsd > 0
  const showMainEstimate = hasAgentSpend || !spend.main.isFromTotal
  const tilesPerRow = input.columns >= TWO_TILES_MIN_COLUMNS ? 2 : 1
  const tileWidth = tilesPerRow === 2 ? '50%' : undefined

  const countsBox = () => (
    <Box key="counts" flexDirection="row" gap={ITEM_GAP} flexShrink={0}>
      <Text bold dimColor={counts.live === 0} color={palette.run}>{'▶' + counts.live}</Text>
      <Text bold dimColor={counts.done === 0} color={palette.done}>{'✓' + counts.done}</Text>
      <Text bold dimColor={counts.failed === 0} color={palette.fail}>{'✕' + counts.failed}</Text>
    </Box>
  )

  const foldButton = (
    <Button key="fold" plain onPress={() => actions.toggleFold()}>
      {isFolded ? '⌄' : '⌃'}
    </Button>
  )

  const legendItem = (arc: Arc) => (
    <Box key={'legend-' + arc.id} flexDirection="row" gap={ITEM_GAP} alignItems="center" flexShrink={0}>
      <Text color={arcColorOf(palette, arc.id)}>●</Text>
      <Text bold>{arc.short}</Text>
      <Text bold={isWarning(arc.percent)} color={toneColorOfPercent(palette, arc.percent)}>{percentTextOf(arc.percent)}</Text>
      {arc.resetsAt === null ? (arc.usage === null ? null : <Text dimColor>{arc.usage.replace(' of ', '/')}</Text>) : <Text dimColor>{'↻' + resetClockOf(arc.resetsAt, now)}</Text>}
    </Box>
  )

  const costText = gauges.costUsd === null ? null : <Box key="cost" flexShrink={0}><Text bold>{formatUsd(gauges.costUsd)}</Text></Box>

  const legendColumn = (column: readonly Arc[], index: number, columns: readonly (readonly Arc[])[]) => {
    const firstColumnLines = (apiText !== null ? 1 : 0) + (columns[0]?.length ?? 0)
    const isCostColumn = index === 1
    const isShorter = column.length < firstColumnLines
    const lastArc = column[column.length - 1]
    const items = column.map((arc, position) => (isCostColumn && !isShorter && position === column.length - 1 ? (
      <Box key={'legend-last-' + arc.id} flexDirection="row" gap={SECTION_GAP} flexShrink={0}>
        {legendItem(arc)}
        {costText}
      </Box>
    ) : legendItem(arc)))

    return (
      <Box key={'legend-column-' + index} flexDirection="column" flexShrink={0}>
        {index === 0 && apiText !== null ? <Text key="api" dimColor>{apiText}</Text> : null}
        {items}
        {isCostColumn && (isShorter || lastArc === undefined) ? costText : null}
      </Box>
    )
  }

  const legend = (
    <Box key="legend" flexDirection="row" gap={SECTION_GAP} flexShrink={0}>
      {legendColumnsOf(arcs).map((column, index, columns) => legendColumn(column, index, columns))}
    </Box>
  )

  const activityText = (activity: Activity) => (
    <Text bold color={colorOfTone(palette, activity.tone)} wrap="truncate-end">
      {activity.icon + ' ' + activity.word}
    </Text>
  )

  const field = (key: string, child: RenderElement, isShrinkable = false) => (
    <Box key={key} flexShrink={isShrinkable ? 1 : 0} minWidth={0} overflow="hidden">
      {child}
    </Box>
  )

  if (isFolded) {
    const miniRows = miniLaneRowsOf({ roster: input.roster, rows: input.rows, now })
    const miniWindow = windowFor(MINI_LANES_RANGE, now, now)
    const mini = miniLanesSvg({ lanes: miniRows.map(row => cellsOf(row, miniWindow, now, MINI_LANE_CELLS)), setting: input.scheme })
    const ring = ringSvg({ arcs, setting: input.scheme })
    const legendColumns = legendColumnsWidthOf({ columns: legendColumnsOf(arcs), now, costUsd: gauges.costUsd, apiText })
    const laneColumns = miniLaneColumnsOf({ columns: input.columns, legendColumns, activity: tiles.main.activity })

    return (
      <Box key="folded" flexDirection="row" alignItems="center" gap={SECTION_GAP} paddingX={FRAME_PAD_X} {...surface}>
        <Box key="ring" flexDirection="row" alignItems="center" gap="sm" flexShrink={0}>
          <Svg source={ring.source} alt={arcs.map(arc => arc.name + ' ' + Math.round(arc.percent) + '%').join(', ')} width={ring.width} height={ring.height} />
          {legend}
        </Box>
        <Box key="main-state" flexDirection="column" flexShrink={0}>
          <Box key="main-line" flexDirection="row" gap={SECTION_GAP}>
            <Text bold>{MAIN_NAME}</Text>
            {countsBox()}
          </Box>
          {activityText(tiles.main.activity)}
        </Box>
        <Box key="mini-lanes" alignSelf="center" flexGrow={1} flexShrink={1} minWidth={0} overflow="hidden">
          <Svg source={mini.source} alt="main and live agents, last 5m" width={pixelsOf(laneColumns)} height={mini.height} />
        </Box>
        {foldButton}
      </Box>
    )
  }

  const gutterArc = (arc: Arc) => {
    const bar = barSvg({ percent: arc.percent, id: arc.id, width: GUTTER_BAR_WIDTH, setting: input.scheme })

    return (
      <Box key={'arc-' + arc.id} flexDirection="column">
        <Box flexDirection="row" justifyContent="space-between" gap={ITEM_GAP}>
          <Box flexDirection="row" gap={ITEM_GAP} flexShrink={0}>
            <Text color={arcColorOf(palette, arc.id)}>●</Text>
            <Text bold>{arc.name}</Text>
            <Text bold={isWarning(arc.percent)} color={toneColorOfPercent(palette, arc.percent)}>{percentTextOf(arc.percent)}</Text>
          </Box>
          {arc.resetsAt === null && arc.usage === null ? null : <Text dimColor>{arc.resetsAt === null ? (arc.usage ?? '') : '↻ ' + resetClockOf(arc.resetsAt, now)}</Text>}
        </Box>
        <Svg source={bar.source} alt={arc.name + ' ' + Math.round(arc.percent) + '%'} width={bar.width} height={bar.height} />
      </Box>
    )
  }

  const spendLine = (key: string, label: string, value: string, isStrong = false) => (
    <Box key={key} flexDirection="row" justifyContent="space-between">
      <Text dimColor>{label}</Text>
      <Text bold={isStrong}>{value}</Text>
    </Box>
  )

  const usdText = (usd: number | null, prefix = ''): string => (usd === null ? '—' : prefix + formatUsd(usd))

  const rule = ruleSvg({ width: GUTTER_BAR_WIDTH, setting: input.scheme })

  const gutter = (
    <Box key="gutter" flexDirection="column" gap={ITEM_GAP} width={GUTTER_COLUMNS} flexShrink={0} paddingX={FRAME_PAD_X} paddingY={ITEM_GAP}>
      {arcs.map(gutterArc)}
      <Svg source={rule.source} alt="" width={rule.width} height={rule.height} />
      <Box key="spend" flexDirection="column">
        {spendLine('spend-session', 'session total', usdText(spend.sessionUsd), true)}
        {showMainEstimate ? spendLine('spend-main', mainEstimateLabelOf(spend.main), usdText(spend.main.usd, '~')) : null}
        {hasAgentSpend ? spendLine('spend-agents', 'agents est.', usdText(spend.agentsUsd, '~')) : null}
        {hasLimits || spend.tokensIn === 0 ? null : spendLine('spend-in', 'tokens in', formatTokens(spend.tokensIn))}
        {hasLimits || spend.tokensOut === 0 ? null : spendLine('spend-out', 'tokens out', formatTokens(spend.tokensOut))}
      </Box>
    </Box>
  )

  const rangeButtons = (
    <Box key="ranges" flexDirection="row" gap={ITEM_GAP} flexShrink={0}>
      {TIMELINE_RANGES.map((name: Range) => (
        <Button key={'range-' + name} variant={name === input.range ? 'primary' : 'secondary'} onPress={() => actions.setRange(name)}>
          {rangeLabelOf(name)}
        </Button>
      ))}
    </Box>
  )

  const header = (
    <Box key="header" flexDirection="row" alignItems="center" gap={SECTION_GAP}>
      {rangeButtons}
      <Box key="spacer" flexGrow={1} />
      <Text dimColor>{AGENTS_LABEL}</Text>
      {countsBox()}
      {foldButton}
    </Box>
  )

  const factRow = (fact: { term: string; value: string }) => (
    <Box key={'fact-' + fact.term} flexDirection="row" gap={SECTION_GAP} justifyContent="space-between">
      <Text dimColor>{fact.term}</Text>
      <Text>{fact.value}</Text>
    </Box>
  )

  const tileCard = (tile: Tile) => (
    <Box position="absolute" top={0} left={0} display="none" hover={{ display: 'flex' }} flexDirection="column" paddingX={FRAME_PAD_X} paddingY={ITEM_GAP} borderStyle="round" borderColor={palette.muted} backgroundColor={colors.selected}>
      <Text bold>{tile.name + ' ' + tile.activity.icon + ' ' + tile.activity.word}</Text>
      {tile.facts.map(factRow)}
    </Box>
  )

  const stripColumns = stripColumnsOf({ columns: input.columns, tilesPerRow })

  const tileBox = (tile: Tile) => {
    const strip = stripSvg({ cells: tile.strip, setting: input.scheme })

    return (
      <Box key={'tile-' + tile.id} flexDirection="column" flexGrow={1} flexShrink={1} width={tileWidth} minWidth={TILE_MIN_COLUMNS} overflow="hidden" paddingX={FRAME_PAD_X} backgroundColor={tile.isWaiting ? palette.warnWash : colors.tint}>
        <Box key={'top-' + tile.id} flexDirection="row" alignItems="center" gap={ITEM_GAP} overflow="hidden">
          {field('name-' + tile.id, <Text bold wrap="truncate-end">{tile.name}</Text>)}
          {tile.model === null ? null : field('model-' + tile.id, <Text dimColor wrap="truncate-end">{tile.model}</Text>)}
          {field('state-' + tile.id, activityText(tile.activity))}
          {field('detail-' + tile.id, <Text dimColor wrap="truncate-end">{tile.activity.detail}</Text>, true)}
        </Box>
        <Box key={'bottom-' + tile.id} flexDirection="row" alignItems="center" gap={SECTION_GAP}>
          <Box key={'strip-' + tile.id} flexGrow={1} flexShrink={1} minWidth={STRIP_MIN_COLUMNS} overflow="hidden">
            <Svg source={strip.source} alt={tile.name + ' activity over the range'} width={pixelsOf(stripColumns)} height={STRIP_HEIGHT} />
          </Box>
          <Box key={'time-' + tile.id} flexShrink={0} minWidth={TIME_COLUMNS} overflow="hidden">
            <Text bold>{tile.time}</Text>
          </Box>
          <Box key={'tokens-' + tile.id} width={TOKENS_COLUMNS} flexShrink={0} justifyContent="flex-end">
            <Text dimColor>{tile.tokens}</Text>
          </Box>
          <Box key={'cost-' + tile.id} width={COST_COLUMNS} flexShrink={0} justifyContent="flex-end">
            <Text bold>{tile.cost}</Text>
          </Box>
        </Box>
        {tileCard(tile)}
      </Box>
    )
  }

  const ghostLine = (ghost: Ghost) =>
    ghost.widensRange ? (
      <Box key="ghost" flexDirection="row" flexShrink={0}>
        <Button key="earlier" plain onPress={() => actions.setRange('session')}>
          {ghost.text}
        </Button>
      </Box>
    ) : (
      <Box key="ghost" flexDirection="row" flexShrink={0}>
        <Text key="ghost-text" dimColor>{ghost.text}</Text>
      </Box>
    )

  const slots = [tileBox(tiles.main), ...tiles.agents.map(tileBox)]

  const tileRows = groupsOf(slots, tilesPerRow).map((pair, index) => (
    <Box key={'tile-row-' + index} flexDirection="row" gap={ITEM_GAP}>
      {pair}
      {pair.length < tilesPerRow ? <Box key="slot" flexGrow={1} flexShrink={1} width={tileWidth} /> : null}
    </Box>
  ))

  const mainColumn = (
    <Box key="main-column" flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0} gap={ITEM_GAP} paddingX={FRAME_PAD_X} paddingY={ITEM_GAP}>
      {header}
      {tileRows}
      {tiles.ghost === null ? null : ghostLine(tiles.ghost)}
    </Box>
  )

  return (
    <Box key="unfolded" flexDirection="row" {...surface}>
      {gutter}
      <Box key="divider" width={1} backgroundColor={palette.rail} />
      {mainColumn}
    </Box>
  )
}
