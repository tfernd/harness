import type { Elements, RenderElement } from 'claude-code'

import type { AgentState } from '../types'

import { DIRECT_GROUP, RANGES, countAgents, formatClock, formatShort, tracedRows } from './model'
import { HIDDEN_KEY, RULE_KEY, TIMELINE_KEY, densityKey, groupRowsKey, groupCountsKey, groupLabelKey, listedGroupsOf } from './svg-band'
import type { BandSvg, SvgInput } from './svg-band'
import { type GaugeSpec, gaugeSpecs, stripDetailOf } from './svg-strip'
import { bandColorsOf } from './svg-theme'
import { type GroupPlan, groupCountsText, groupTitleOf, liveStateCounts } from './svg-timeline'
import type { Actions } from './view'

export type SvgTable = Elements['desktop'] | Elements['vscode'] | Elements['mobile']

export type DesktopView = {
  ui: SvgTable
  svgs: ReadonlyMap<string, BandSvg>
  input: SvgInput
  actions: Actions
}

const STATE_COLOR: Record<AgentState, string> = {
  launched: 'inactive',
  thinking: 'suggestion',
  tool: 'success',
  waiting: 'warning',
  done: 'inactive',
  failed: 'error',
}

const foldedDetailOf = (spec: GaugeSpec): string => spec.detail.replace(/\s*↻.*$/, '')

const statusOf = (input: SvgInput): { word: string; state: AgentState } => {
  if (input.isWorking) {
    return { word: 'WORKING', state: 'thinking' }
  }

  return [...input.rows.values()].some(row => row.state === 'waiting')
    ? { word: 'WAITING', state: 'waiting' }
    : { word: 'IDLE', state: 'launched' }
}

const captionOf = (input: SvgInput): string => {
  if (input.isWorking && input.turnStartedAt !== null) {
    return `turn ${formatClock(input.now - input.turnStartedAt)}`
  }

  return input.gauges.sessionStartedAt === null ? '' : `up ${formatShort(input.now - input.gauges.sessionStartedAt)}`
}

const HEADER_PAD_COLUMNS = 2
const CHEVRON_COLUMNS = 3
const FRAME_PAD_X = 'sm'
const SECTION_GAP = 'sm'
const ITEM_GAP = 'xs'

export const buildDesktopBand = (view: DesktopView): RenderElement => {
  const { Box, Text, Button, Svg } = view.ui
  const { input, actions } = view
  const { isFolded } = input
  const live = tracedRows(input.roster.rows, input.rows, input.now)
  const counts = countAgents(input.roster.rows, { done: input.roster.evictedDone, failed: input.roster.evictedFailed })
  const status = statusOf(input)
  const specs = gaugeSpecs(input.gauges, input.now)
  const detailOf = isFolded
    ? foldedDetailOf
    : stripDetailOf(specs, {
        width: input.width,
        statusChars: Math.max(status.word.length, captionOf(input).length),
        countsChars: `${counts.done} done`.length + 2,
      })

  const colors = bandColorsOf(input.scheme)
  const fill = (color: string | undefined) => (color === undefined ? {} : { backgroundColor: color })
  const tinted = fill(colors?.tint)

  const svgOf = (key: string, alt: string) => {
    const svg = view.svgs.get(key)

    return svg === undefined || svg.height === 0 ? null : <Svg key={key} source={svg.source} alt={alt} width={svg.width} height={svg.height} />
  }

  const ruleFor = (key: string) => {
    const svg = view.svgs.get(RULE_KEY)

    return svg === undefined ? null : <Svg key={key} source={svg.source} alt="divider" width={svg.width} height={svg.height} />
  }

  const gaugeBox = (spec: GaugeSpec) => (
    <Box key={`gauge-${spec.id}`} flexDirection="row" gap={ITEM_GAP} alignItems="center">
      {svgOf(`ring-${spec.id}`, `${spec.name} ${Math.round(spec.percent)}%`)}
      <Box flexDirection="column">
        <Text bold wrap="truncate-end">
          {spec.name}
        </Text>
        <Text dimColor={!spec.isDetailUrgent} color={spec.isDetailUrgent ? 'error' : undefined} wrap="truncate-end">
          {detailOf(spec)}
        </Text>
      </Box>
      <Box position="absolute" top={-2} left={0} display="none" hover={{ display: 'flex' }} borderStyle="round" paddingX={1}>
        <Text>{spec.tip}</Text>
      </Box>
    </Box>
  )

  const foldButton = (
    <Button key="fold" plain onPress={() => actions.toggleFold()}>
      {isFolded ? '▾' : '▴ fold'}
    </Button>
  )

  const rangeControl = (
    <Box key="ranges" flexDirection="row" gap={SECTION_GAP} alignItems="center">
      <Text dimColor>range</Text>
      <Box flexDirection="row" gap={SECTION_GAP}>
        {RANGES.map(name =>
          name === input.range ? (
            <Text key={`range-${name}`} bold underline>
              {name}
            </Text>
          ) : (
            <Button key={`range-${name}`} plain dimColor onPress={() => actions.setRange(name)}>
              {name}
            </Button>
          ),
        )}
      </Box>
    </Box>
  )

  const groupHeader = (group: GroupPlan) => {
    const { kind, name } = groupTitleOf(group)
    const ended = group.counts.done + group.counts.failed
    const key = `group-header-${group.id}`
    const toggle = (
      <Box key={`group-toggle-${group.id}`} width={CHEVRON_COLUMNS} flexShrink={0}>
        <Button key={`group-button-${group.id}`} plain onPress={() => actions.toggleGroup(group.id)}>
          <Text>{group.isFolded ? '∨' : '∧'}</Text>
        </Button>
      </Box>
    )
    const title = svgOf(groupLabelKey(group.id), `${kind} ${name}`)

    if (!group.isFolded) {
      return (
        <Box key={key} flexDirection="row" alignItems="center" {...tinted}>
          {toggle}
          {title}
          <Box flexGrow={1} flexShrink={1} justifyContent="flex-end" paddingRight={HEADER_PAD_COLUMNS}>
            <Text dimColor wrap="truncate-end">{`${group.counts.live} live · ${ended} ended`}</Text>
          </Box>
        </Box>
      )
    }

    const counts = liveStateCounts(input.rows, group.agents)
    const text = groupCountsText(counts, ended)

    return (
      <Box key={key} flexDirection="row" alignItems="center" {...tinted}>
        {toggle}
        {title}
        {svgOf(densityKey(group.id), `${group.name}: agents per state over ${input.range}`)}
        {svgOf(groupCountsKey(group.id), `${group.name}: agents by state now`) ?? (
          <Box flexGrow={1} flexShrink={1} overflow="hidden" paddingLeft={HEADER_PAD_COLUMNS}>
            <Text dimColor wrap="truncate-end">
              {text}
            </Text>
          </Box>
        )}
      </Box>
    )
  }

  const timelineRegion = (
    <Box key="timeline" flexDirection="column">
      {svgOf(TIMELINE_KEY, `Agent timeline over ${input.range}`)}
      {listedGroupsOf(input).flatMap(group => [
        ruleFor(`rule-${group.id}`),
        groupHeader(group),
        group.isFolded ? null : svgOf(groupRowsKey(group.id), `Agent rows: ${group.name}`),
      ])}
      {svgOf(HIDDEN_KEY, 'Agents not drawn')}
    </Box>
  )

  const statusBox = (
    <Box key="status" flexDirection="column">
      <Text bold color={STATE_COLOR[status.state]} wrap="truncate-end">
        {status.word}
      </Text>
      <Text dimColor wrap="truncate-end">
        {captionOf(input)}
      </Text>
    </Box>
  )

  const countsInline = (
    <Box key="counts" flexDirection="row" gap="xs" flexShrink={0}>
      <Text bold color="success" wrap="truncate-end">{`${counts.live} live ·`}</Text>
      <Text dimColor wrap="truncate-end">{`${counts.done} ✓ ·`}</Text>
      <Text color={counts.failed > 0 ? 'error' : undefined} dimColor={counts.failed === 0} wrap="truncate-end">{`${counts.failed} ✗`}</Text>
    </Box>
  )

  const countRow = (mark: string, markColor: string | undefined, text: string, isDim: boolean, textColor?: string) => (
    <Box key={`count-${mark}`} flexDirection="row" gap="xs" alignItems="center">
      <Text color={markColor} dimColor={markColor === undefined}>
        {mark}
      </Text>
      <Text bold={!isDim} dimColor={isDim} color={textColor} wrap="truncate-end">
        {text}
      </Text>
    </Box>
  )

  const countsStacked = (
    <Box key="counts" flexDirection="column" flexShrink={0}>
      {countRow('●', STATE_COLOR.thinking, `${counts.live} live`, false)}
      {countRow('✓', undefined, `${counts.done} done`, true)}
      {countRow('✗', counts.failed > 0 ? 'error' : undefined, `${counts.failed} fail`, counts.failed === 0, counts.failed > 0 ? 'error' : undefined)}
    </Box>
  )

  if (isFolded) {
    return (
      <Box flexDirection="row" alignItems="center" gap="md" borderStyle="round" borderColor={colors?.frame ?? 'promptBorder'} paddingX={FRAME_PAD_X} {...fill(colors?.surface)}>
        {foldButton}
        {statusBox}
        {specs.map(gaugeBox)}
        {live.length === 0 ? null : svgOf('traces', `${live.length} live agent traces, last 60s`)}
        <Box key="spacer" flexGrow={1} />
        {countsInline}
      </Box>
    )
  }

  const frameColor = colors?.frame ?? 'promptBorder'
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={frameColor} {...fill(colors?.surface)}>
      <Box key="controls" flexDirection="row" alignItems="center" gap={SECTION_GAP} paddingX={FRAME_PAD_X} paddingY="xs">
        {foldButton}
        {rangeControl}
      </Box>
      {ruleFor('rule-controls')}
      <Box key="strip" flexDirection="row" alignItems="center" justifyContent="space-between" gap={SECTION_GAP} paddingX={FRAME_PAD_X} paddingY="xs">
        {statusBox}
        {specs.map(gaugeBox)}
        {countsStacked}
      </Box>
      {timelineRegion}
    </Box>
  )
}
