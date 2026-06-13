import typescript from '@rollup/plugin-typescript';
import virtual from '@rollup/plugin-virtual';
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

// Read PANEL_VERSION from const.py — single source of truth (release.yml asserts
// this matches manifest.json's version).
const constPy = resolve(dirname(fileURLToPath(import.meta.url)), '../const.py');
let PANEL_VERSION = '0.0.0';
try {
  const contents = readFileSync(constPy, 'utf8');
  const versionMatch = contents.match(/PANEL_VERSION\s*=\s*"([^"]+)"/);
  if (versionMatch) {
    PANEL_VERSION = versionMatch[1];
  } else {
    console.warn('Warning: PANEL_VERSION not found in const.py, using default 0.0.0');
  }
} catch (err) {
  console.error(`Error reading PANEL_VERSION from ${constPy}:`, err.message);
  throw new Error(`Failed to read version from const.py: ${err.message}`);
}

export default {
  input: 'src/index.ts',
  output: {
    file: 'home-keeper-panel.js',
    format: 'iife',
    name: 'HomeKeeperPanelBundle',
    banner: `/**\n * Home Keeper panel — home maintenance & chores for Home Assistant.\n * Bundled with the Home Keeper integration — no manual setup required.\n * Version: ${PANEL_VERSION}\n * Built: ${new Date().toISOString().split('T')[0]}\n */`,
  },
  plugins: [
    typescript({ tsconfig: './tsconfig.json' }),
    virtual({
      'panel-version': `export const PANEL_VERSION = '${PANEL_VERSION}';`,
    }),
  ],
};
