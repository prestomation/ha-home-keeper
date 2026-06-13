import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    include: [
      'tests/frontend/**/*.test.js',
      'custom_components/home_keeper/frontend/test/**/*.test.js',
    ],
  },
});
