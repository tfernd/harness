import type { Elements, RenderElement } from 'claude-code'

import type { AgentState } from '../types'

import { RANGES, countAgents, tracedRows } from './model'
import { COUNTS_KEY, captionOf, statusOf, HIDDEN_KEY, RULE_KEY, TIMELINE_KEY, densityKey, groupLabelColumnOf, groupRowsKey, groupCountsKey, listedGroupsOf, timelineInputOf } from './svg-band'
import type { BandSvg, SvgInput } from './svg-band'
import { type GaugeSpec, gaugeSpecs, stripDetailOf } from './svg-strip'
import { bandColorsOf } from './svg-theme'
import { type GroupPlan, groupCountsText, groupCountsWidthOf, groupTitleOf, liveStateCounts } from './svg-timeline'
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

const HEADER_PAD_COLUMNS = 2
const PX_PER_COLUMN = 8
const RING_SLOT_COLUMNS = 4
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
        countsChars: 4,
      })

  const colors = bandColorsOf(input.scheme)
  const fill = (color: string | undefined) => (color === undefined ? {} : { backgroundColor: color })
  const tinted = fill(colors.tint)
  const labelColumns = Math.round(groupLabelColumnOf(input) / PX_PER_COLUMN)
  const stateColumns = Math.round(groupCountsWidthOf(timelineInputOf(input)) / PX_PER_COLUMN)

  const svgOf = (key: string, alt: string) => {
    const svg = view.svgs.get(key)

    return svg === undefined || svg.height === 0 ? null : <Svg key={key} source={svg.source} alt={alt} width={svg.width} height={svg.height} />
  }

  const ruleFor = (key: string) => {
    const svg = view.svgs.get(RULE_KEY)

    return svg === undefined ? null : <Svg key={key} source={svg.source} alt="divider" width={svg.width} height={svg.height} />
  }

  const gaugeBox = (spec: GaugeSpec) => (
    <Box key={`gauge-${spec.id}`} flexDirection="row" gap={ITEM_GAP} alignItems="center" flexShrink={0}>
      {svgOf(`ring-${spec.id}`, `${spec.name} ${Math.round(spec.percent)}%`) ?? <Box key={`slot-${spec.id}`} width={RING_SLOT_COLUMNS} flexShrink={0} />}
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

  const gaugeGroup = (
    <Box key="gauges" flexDirection="row" gap="md" alignItems="center" flexShrink={0}>
      {specs.map(gaugeBox)}
    </Box>
  )

  const foldButton = (
    <Button key="fold" plain onPress={() => actions.toggleFold()}>
      {isFolded ? '▾' : '▴ fold'}
    </Button>
  )

  const nextRange = RANGES[(RANGES.indexOf(input.range) + 1) % RANGES.length] ?? RANGES[0]

  const rangeControl = (
    <Button key="range" plain onPress={() => (nextRange === undefined ? undefined : actions.setRange(nextRange))}>
      {`range ${input.range} ▾`}
    </Button>
  )

  const groupHeader = (group: GroupPlan) => {
    const { kind, name } = groupTitleOf(group)
    const ended = group.counts.done + group.counts.failed
    const key = `group-header-${group.id}`
    const toggle = (
      <Box key={`group-toggle-${group.id}`} width={labelColumns} flexShrink={0} overflow="hidden">
        <Button key={`group-button-${group.id}`} plain onPress={() => actions.toggleGroup(group.id)}>
          {`${group.isFolded ? '∨' : '∧'} ${kind} ${name}`}
        </Button>
      </Box>
    )

    if (!group.isFolded) {
      return (
        <Box key={key} flexDirection="row" alignItems="center" {...tinted}>
          {toggle}
          <Box flexGrow={1} flexShrink={1} />
          <Box
            key={`group-counts-${group.id}`}
            width={stateColumns === 0 ? undefined : stateColumns}
            flexShrink={0}
            paddingLeft={stateColumns === 0 ? 0 : HEADER_PAD_COLUMNS}
            paddingRight={stateColumns === 0 ? HEADER_PAD_COLUMNS : 0}
          >
            <Text dimColor wrap="truncate-end">{`${group.counts.live} live · ${ended} ended`}</Text>
          </Box>
        </Box>
      )
    }

    const counts = liveStateCounts(input.rows, group.agents)
    const text = groupCountsText(counts, ended)
    const density = svgOf(densityKey(group.id), `${group.name}: agents per state over ${input.range}`)

    return (
      <Box key={key} flexDirection="row" alignItems="center" {...tinted}>
        {toggle}
        {density === null ? null : (
          <Box key={`group-density-${group.id}`} alignSelf="center" flexShrink={0}>
            {density}
          </Box>
        )}
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

  const countsSvg = svgOf(COUNTS_KEY, `${counts.live} live, ${counts.done} done, ${counts.failed} failed`)
  const countsBox =
    countsSvg === null ? null : (
      <Box key="counts-slot" alignSelf="center" flexShrink={0}>
        {countsSvg}
      </Box>
    )

  if (isFolded) {
    return (
      <Box flexDirection="row" alignItems="center" gap="md" paddingX={FRAME_PAD_X} {...fill(colors.surface)}>
        {foldButton}
        {statusBox}
        {gaugeGroup}
        {live.length === 0 ? null : (
          <Box key="traces-slot" alignSelf="center" flexShrink={1} minWidth={0} overflow="hidden">
            {svgOf('traces', `${live.length} live agent traces, last 60s`)}
          </Box>
        )}
        <Box key="spacer" flexGrow={1} />
        {countsBox}
      </Box>
    )
  }

  return (
    <Box flexDirection="column" paddingBottom={ITEM_GAP} {...fill(colors.surface)}>
      <Box key="controls" flexDirection="row" alignItems="center" gap="md" paddingX={FRAME_PAD_X} paddingBottom="xs">
        {foldButton}
        {rangeControl}
      </Box>
      {ruleFor('rule-controls')}
      <Box key="strip" flexDirection="row" alignItems="center" gap="md" paddingX={FRAME_PAD_X} paddingY="xs">
        {statusBox}
        {gaugeGroup}
        <Box key="spacer" flexGrow={1} />
        {countsBox}
      </Box>
      {timelineRegion}
    </Box>
  )
}
