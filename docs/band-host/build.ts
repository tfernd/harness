import { dirname, join } from 'node:path'

const HOST_DIRECTORY = import.meta.dir
const DOCS_DIRECTORY = dirname(HOST_DIRECTORY)
const ENGINE_PATH = join(HOST_DIRECTORY, 'engine.ts')
const JSX_RUNTIME_PATH = join(HOST_DIRECTORY, 'jsx-runtime.ts')

const result = await Bun.build({
  entrypoints: [join(HOST_DIRECTORY, 'main.ts')],
  outdir: DOCS_DIRECTORY,
  naming: 'band-view.js',
  target: 'browser',
  format: 'iife',
  minify: true,
  plugins: [
    {
      name: 'fake-claude-code',
      setup: build => {
        build.onResolve({ filter: /^claude-code$/ }, () => ({ path: ENGINE_PATH }))
        build.onResolve({ filter: /^react\/jsx-(dev-)?runtime$/ }, () => ({ path: JSX_RUNTIME_PATH }))
      },
    },
  ],
})

if (!result.success) {
  for (const log of result.logs) {
    console.error(log)
  }

  process.exit(1)
}
