import type { Elements, RenderElement } from 'claude-code'

import type { AgentState } from '../types'

import { DIRECT_GROUP, RANGES, countAgents, formatClock, formatShort, tracedRows } from './model'
import { HIDDEN_KEY, TIMELINE_KEY, groupRowsKey, listedGroupsOf } from './svg-band'
import type { BandSvg, SvgInput } from './svg-band'
import { type GaugeSpec, gaugeSpecs, stripDetailOf } from './svg-strip'
import type { GroupPlan } from './svg-timeline'
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
        countsChars: `${counts.live} live · ${counts.done} ✓ · ${counts.failed} ✗`.length,
      })

  const svgOf = (key: string, alt: string) => {
    const svg = view.svgs.get(key)

    return svg === undefined || svg.height === 0 ? null : <Svg key={key} source={svg.source} alt={alt} width={svg.width} height={svg.height} />
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
  )

  const groupHeader = (group: GroupPlan) => {
    const kind = group.id === DIRECT_GROUP ? 'DIRECT' : 'WORKFLOW'
    const name = group.name.replace(/^workflow /, '')

    return (
      <Box key={`group-header-${group.id}`} flexDirection="row" alignItems="center" gap={SECTION_GAP} paddingX={FRAME_PAD_X}>
        <Box flexGrow={1} flexShrink={1}>
          <Button key={`group-button-${group.id}`} plain onPress={() => actions.toggleGroup(group.id)}>
            <Text>{group.isFolded ? '▸ ' : '▾ '}</Text>
            <Text dimColor bold>{`${kind} `}</Text>
            <Text>{name}</Text>
          </Button>
        </Box>
        <Text dimColor wrap="truncate-end">{`${group.counts.live} live · ${group.counts.done + group.counts.failed} ended`}</Text>
      </Box>
    )
  }

  const timelineRegion = (
    <Box key="timeline" flexDirection="column">
      {svgOf(TIMELINE_KEY, `Agent timeline over ${input.range}`)}
      {listedGroupsOf(input).flatMap(group => [
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

  if (isFolded) {
    return (
      <Box flexDirection="row" alignItems="center" gap="md" borderStyle="round" paddingX={FRAME_PAD_X}>
        {foldButton}
        {statusBox}
        {specs.map(gaugeBox)}
        {live.length === 0 ? null : svgOf('traces', `${live.length} live agent traces, last 60s`)}
        <Box key="spacer" flexGrow={1} />
        {countsInline}
      </Box>
    )
  }

  return (
    <Box flexDirection="column" borderStyle="round">
      <Box key="controls" flexDirection="row" alignItems="center" gap={SECTION_GAP} paddingX={FRAME_PAD_X}>
        {foldButton}
        {rangeControl}
        <Box key="spacer" flexGrow={1} />
      </Box>
      <Box key="strip" flexDirection="row" alignItems="center" gap={SECTION_GAP} paddingX={FRAME_PAD_X}>
        {statusBox}
        {specs.map(gaugeBox)}
        <Box key="spacer" flexGrow={1} />
        {countsInline}
      </Box>
      {timelineRegion}
    </Box>
  )
}
