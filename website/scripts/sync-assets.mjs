// Copies the integration's committed screenshots (../docs/images) into the
// Docusaurus static tree so docs can reference them via /img/screenshots/<file>.
// docs/images remains the single home for screenshots (and the AGENTS.md "UI PRs
// need screenshots" gate keeps capturing there), so the site has no second copy
// to keep in sync — it just mirrors them at build/start time.
import {cp, mkdir, rm} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, '..', '..', 'docs', 'images');
const dest = resolve(here, '..', 'static', 'img', 'screenshots');

if (!existsSync(src)) {
  console.warn(`[sync-assets] source not found, skipping: ${src}`);
  process.exit(0);
}

await rm(dest, {recursive: true, force: true});
await mkdir(dest, {recursive: true});
await cp(src, dest, {recursive: true});
console.log(`[sync-assets] copied screenshots -> ${dest}`);
