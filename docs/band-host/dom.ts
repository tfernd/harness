import type { Child, Payload, ViewNode } from './engine'

const COLUMN_PX = 8
const ROW_PX = 18

const SPACE_PX: Readonly<Record<string, number>> = { xs: 4, sm: 12, md: 16, lg: 24, xl: 32 }

const TAG_OF_TYPE: Readonly<Record<string, string>> = { Box: 'div', Text: 'span', Button: 'button', Svg: 'img' }

const CLASS_OF_TYPE: Readonly<Record<string, string>> = { Box: 'band-box', Text: 'band-text', Button: 'band-button', Svg: 'band-image' }

const TRUNCATING_WRAPS: readonly string[] = ['truncate', 'truncate-end', 'truncate-start', 'truncate-middle', 'end', 'middle']

const FLEX_SIDES: Readonly<Record<string, string>> = { 'flex-start': 'flex-start', 'flex-end': 'flex-end', center: 'center', stretch: 'stretch', auto: 'auto', 'space-between': 'space-between', 'space-around': 'space-around', 'space-evenly': 'space-evenly' }

const stringOf = (value: unknown): string | undefined => (typeof value === 'string' ? value : undefined)

const numberOf = (value: unknown): number | undefined => (typeof value === 'number' ? value : undefined)

const recordOf = (value: unknown): Payload => (typeof value === 'object' && value !== null ? value : {})

const spaceOf = (value: unknown): string | undefined => {
  if (typeof value === 'number') {
    return `${value * COLUMN_PX}px`
  }

  const step = typeof value === 'string' ? SPACE_PX[value] : undefined

  return step === undefined ? undefined : `${step}px`
}

const sizeOf = (value: unknown): string | undefined => (typeof value === 'number' ? `${value * COLUMN_PX}px` : stringOf(value))

const declaration = (name: string, value: string | number | undefined): string[] => (value === undefined ? [] : [`${name}:${value}`])

const spacingDeclarations = (props: Payload, group: 'padding' | 'margin'): string[] => {
  const key = (suffix: string): unknown => props[group + suffix]
  const sides: readonly [string, readonly string[]][] = [
    ['', ['top', 'right', 'bottom', 'left']],
    ['X', ['left', 'right']],
    ['Y', ['top', 'bottom']],
    ['Top', ['top']],
    ['Bottom', ['bottom']],
    ['Left', ['left']],
    ['Right', ['right']],
  ]

  return sides.flatMap(([suffix, edges]) => edges.flatMap(edge => declaration(`${group}-${edge}`, spaceOf(key(suffix)))))
}

const hasReveal = (props: Payload): boolean => stringOf(props['display']) === 'none' && stringOf(recordOf(props['hover'])['display']) === 'flex'

const boxStyle = (props: Payload, hasHiddenCard: boolean): string => {
  const borderStyle = stringOf(props['borderStyle'])
  const isAbsolute = stringOf(props['position']) === 'absolute'
  const display = stringOf(props['display']) === 'none' && !hasReveal(props) ? 'none' : undefined

  return [
    ...declaration('display', display),
    ...declaration('flex-direction', stringOf(props['flexDirection'])),
    ...declaration('flex-grow', numberOf(props['flexGrow'])),
    ...declaration('flex-shrink', numberOf(props['flexShrink'])),
    ...declaration('flex-wrap', stringOf(props['flexWrap'])),
    ...declaration('align-items', FLEX_SIDES[stringOf(props['alignItems']) ?? '']),
    ...declaration('align-self', FLEX_SIDES[stringOf(props['alignSelf']) ?? '']),
    ...declaration('justify-content', FLEX_SIDES[stringOf(props['justifyContent']) ?? '']),
    ...declaration('gap', spaceOf(props['gap'])),
    ...declaration('column-gap', spaceOf(props['columnGap'])),
    ...declaration('row-gap', spaceOf(props['rowGap'])),
    ...declaration('width', sizeOf(props['width'])),
    ...declaration('height', sizeOf(props['height'])),
    ...declaration('min-width', sizeOf(props['minWidth'])),
    ...declaration('min-height', sizeOf(props['minHeight'])),
    ...spacingDeclarations(props, 'margin'),
    ...spacingDeclarations(props, 'padding'),
    ...(borderStyle === undefined ? [] : ['border:1px solid ' + (stringOf(props['borderColor']) ?? 'currentcolor'), 'border-radius:6px']),
    ...declaration('background-color', stringOf(props['backgroundColor'])),
    ...declaration('overflow', stringOf(props['overflow']) === 'hidden' && !hasHiddenCard ? 'hidden' : undefined),
    ...(isAbsolute ? ['position:absolute', ...declaration('top', numberOf(props['top']) === undefined ? undefined : `${(numberOf(props['top']) ?? 0) * ROW_PX}px`), ...declaration('left', numberOf(props['left']) === undefined ? undefined : `${(numberOf(props['left']) ?? 0) * COLUMN_PX}px`)] : []),
  ].join(';')
}

const textStyle = (props: Payload): string => {
  const isDim = props['dimColor'] === true

  return [
    ...declaration('color', stringOf(props['color'])),
    ...declaration('opacity', isDim ? 0.6 : undefined),
    ...declaration('font-weight', props['bold'] === true ? 700 : undefined),
    ...declaration('font-style', props['italic'] === true ? 'italic' : undefined),
    ...declaration('text-decoration', props['underline'] === true ? 'underline' : undefined),
    ...declaration('background-color', stringOf(props['backgroundColor'])),
  ].join(';')
}

const keyOf = (child: Child): string | undefined => (typeof child === 'string' ? undefined : stringOf(child.props['key']))

const presses = new WeakMap<Element, () => void>()
const appliedStyles = new WeakMap<Element, string>()

const setStyle = (element: HTMLElement, style: string): void => {
  if (appliedStyles.get(element) !== style) {
    appliedStyles.set(element, style)
    element.style.cssText = style
  }
}

const setAttribute = (element: Element, name: string, value: string | undefined): void => {
  if (value === undefined) {
    element.removeAttribute(name)
  } else if (element.getAttribute(name) !== value) {
    element.setAttribute(name, value)
  }
}

const svgDataUri = (source: string): string => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(source)

const createElement = (node: ViewNode): HTMLElement => {
  const tag = TAG_OF_TYPE[node.type]
  const className = CLASS_OF_TYPE[node.type]

  if (tag === undefined || className === undefined) {
    throw new Error(`The band drew an element of type "${node.type}", which the page renderer does not know.`)
  }

  const element = document.createElement(tag)
  element.className = className
  element.dataset['type'] = node.type

  return element
}

const applyProps = (element: HTMLElement, node: ViewNode): void => {
  const { props } = node
  const key = keyOf(node)

  if (key === undefined) {
    delete element.dataset['key']
  } else {
    element.dataset['key'] = key
  }

  if (node.type === 'Box') {
    const hasHiddenCard = node.children.some(child => typeof child !== 'string' && hasReveal(child.props))
    setStyle(element, boxStyle(props, hasHiddenCard))
    setAttribute(element, 'data-reveal', hasReveal(props) ? '' : undefined)

    return
  }

  if (node.type === 'Text') {
    const wrap = stringOf(props['wrap'])
    setStyle(element, textStyle(props))
    setAttribute(element, 'data-wrap', wrap === undefined ? undefined : TRUNCATING_WRAPS.includes(wrap) ? 'truncate' : wrap)

    return
  }

  if (node.type === 'Button') {
    setAttribute(element, 'type', 'button')
    setAttribute(element, 'data-variant', stringOf(props['variant']))
    const onPress = props['onPress']

    if (typeof onPress === 'function') {
      presses.set(element, () => void onPress())
    } else {
      presses.delete(element)
    }

    return
  }

  const width = numberOf(props['width'])
  const height = numberOf(props['height'])
  setStyle(element, [...declaration('width', width === undefined ? undefined : `${width}px`), ...declaration('height', height === undefined ? undefined : `${height}px`)].join(';'))
  setAttribute(element, 'alt', stringOf(props['alt']) ?? '')
  setAttribute(element, 'draggable', 'false')
  const source = stringOf(props['source'])

  if (source !== undefined) {
    const uri = svgDataUri(source)

    if (element.getAttribute('src') !== uri) {
      element.setAttribute('src', uri)
    }
  }
}

const isReusable = (candidate: ChildNode, child: Child): boolean => {
  if (typeof child === 'string') {
    return candidate.nodeType === Node.TEXT_NODE
  }

  return candidate instanceof HTMLElement && candidate.dataset['type'] === child.type
}

const reconcile = (parent: HTMLElement, wanted: readonly Child[]): void => {
  const keyed = new Map<string, HTMLElement>()
  const unkeyed: ChildNode[] = []

  for (const existing of parent.childNodes) {
    const key = existing instanceof HTMLElement ? existing.dataset['key'] : undefined

    if (existing instanceof HTMLElement && key !== undefined) {
      keyed.set(key, existing)
    } else {
      unkeyed.push(existing)
    }
  }

  const result = wanted.map((child): ChildNode => {
    const key = keyOf(child)
    const candidate = key === undefined ? unkeyed.shift() : keyed.get(key)

    if (key !== undefined) {
      keyed.delete(key)
    }

    if (typeof child === 'string') {
      const textNode = candidate !== undefined && isReusable(candidate, child) ? candidate : document.createTextNode(child)

      if (textNode.textContent !== child) {
        textNode.textContent = child
      }

      return textNode
    }

    const element = candidate instanceof HTMLElement && isReusable(candidate, child) ? candidate : createElement(child)
    applyProps(element, child)

    if (child.type !== 'Svg') {
      reconcile(element, child.children)
    }

    return element
  })

  result.forEach((node, index) => {
    if (parent.childNodes[index] !== node) {
      parent.insertBefore(node, parent.childNodes[index] ?? null)
    }
  })

  while (parent.childNodes.length > result.length) {
    parent.lastChild?.remove()
  }
}

export type BandView = { show: (tree: Child | null) => void }

export const createBandView = (root: HTMLElement): BandView => {
  root.addEventListener('click', event => {
    const target = event.target instanceof Element ? event.target.closest('button') : null

    if (target !== null && root.contains(target)) {
      presses.get(target)?.()
    }
  })

  return { show: tree => reconcile(root, tree === null ? [] : [tree]) }
}
