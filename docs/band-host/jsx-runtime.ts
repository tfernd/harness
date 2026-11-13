import { h, type Payload, type ViewNode } from './engine'

const jsxOf = (type: string, props: Payload | null): ViewNode => {
  const { children, ...rest } = props ?? {}
  const list = children === undefined ? [] : Array.isArray(children) ? children : [children]
  return h(type, rest, ...list)
}

export const jsx = jsxOf
export const jsxs = jsxOf
export const jsxDEV = jsxOf
export const Fragment = 'Fragment'
