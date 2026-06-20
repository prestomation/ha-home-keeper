import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: {
    alias: {
      // `panel-version` is a Rollup virtual module at build time (see
      // frontend/rollup.config.mjs); stub it for vitest so panel.ts imports.
      'panel-version': new URL(
        './tests/frontend/stubs/panel-version.js',
        import.meta.url,
      ).pathname,
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: [
      'tests/frontend/**/*.test.js',
      'custom_components/home_keeper/frontend/test/**/*.test.js',
    ],
  },
});
