// The scanner behind `destructive-scan-parity.test.js`.
//
// It reads the TypeScript of the panel and the card as text and finds each place that
// calls a function which deletes, removes or replaces data. A call is safe when it sits
// inside a `confirmDestructive(...)` or `mountConfirm(...)` call (so the confirm button
// runs it), or inside another destructive function (whose own callers are checked in
// turn), or has an entry in the allowlist with a written reason.
//
// It is a text scan, not a type check. It cannot see a call that goes through a
// variable, and it ignores code inside template literals. Its job is the common slip:
// a new delete button that calls the action at once.

/** A function that deletes or removes something is named like one. */
export const DESTRUCTIVE_NAME = /^_?(delete|remove|clear|purge|discard)(?=[A-Z0-9_]|$)/;

/** Destructive by effect, not by name. */
export const EXTRA_NAMES = ['_runImport', 'archiveAsset', '_archiveAsset', 'importData', 'importUpload'];

/** A call on one of these is ours. A call on any other receiver (`set.delete`,
 *  `node.remove`) is the platform's, and the scan leaves it alone. */
export const RECEIVERS = ['api', 'p', 'this', 'host', 'panel', 'state'];

/** Files that only declare types. */
export const TYPE_ONLY = ['panel-host.ts', 'types.ts'];

/** The calls whose arguments run only after a "yes". */
export const GUARDS = ['confirmDestructive', 'mountConfirm'];

const KEYWORDS = new Set(['if', 'for', 'while', 'switch', 'catch', 'function', 'return', 'new']);

/**
 * Replace comments and the inside of strings, templates and regular expressions with
 * spaces, and keep every other character and every newline, so an offset in the result
 * is an offset in the source.
 */
export function blank(src) {
  const out = src.split('');
  let i = 0;
  const wipe = (from, to) => {
    for (let k = from; k < to; k += 1) if (out[k] !== '\n') out[k] = ' ';
  };
  let prev = '';
  while (i < src.length) {
    const c = src[i];
    const d = src[i + 1];
    if (c === '/' && d === '/') {
      const end = src.indexOf('\n', i);
      const to = end < 0 ? src.length : end;
      wipe(i, to);
      i = to;
    } else if (c === '/' && d === '*') {
      const end = src.indexOf('*/', i + 2);
      const to = end < 0 ? src.length : end + 2;
      wipe(i, to);
      i = to;
    } else if (c === "'" || c === '"' || c === '`') {
      let k = i + 1;
      while (k < src.length && src[k] !== c) k += src[k] === '\\' ? 2 : 1;
      wipe(i + 1, k);
      i = k + 1;
      prev = c;
    } else if (c === '/' && /[(,=:[!&|?{};]|^$/.test(prev)) {
      // A regular expression literal: skip to the closing slash, outside a class.
      let k = i + 1;
      let inClass = false;
      while (k < src.length && src[k] !== '\n') {
        if (src[k] === '\\') k += 2;
        else {
          if (src[k] === '[') inClass = true;
          else if (src[k] === ']') inClass = false;
          else if (src[k] === '/' && !inClass) break;
          k += 1;
        }
      }
      wipe(i + 1, k);
      i = k + 1;
      prev = '/';
    } else {
      if (!/\s/.test(c)) prev = c;
      i += 1;
    }
  }
  return out.join('');
}

/** The index of the bracket that closes the one at *open*, or -1. */
export function matching(code, open) {
  const pairs = { '(': ')', '{': '}', '[': ']' };
  const stack = [];
  for (let i = open; i < code.length; i += 1) {
    const c = code[i];
    if (pairs[c]) stack.push(pairs[c]);
    else if (c === ')' || c === '}' || c === ']') {
      if (stack.pop() !== c) return -1;
      if (!stack.length) return i;
    }
  }
  return -1;
}

/** The named functions of a file, each with the range of its body. */
export function functionsOf(code) {
  const found = [];
  const add = (name, from) => {
    const brace = code.indexOf('{', from);
    if (brace < 0 || KEYWORDS.has(name)) return;
    const end = matching(code, brace);
    if (end > brace) found.push({ name, start: brace, end });
  };
  let m;
  const decl = /\bfunction\s+(\w+)\s*(?:<[^>]*>)?\s*\(/g;
  while ((m = decl.exec(code))) {
    const close = matching(code, m.index + m[0].length - 1);
    if (close > 0) add(m[1], close);
  }
  const method = /(?:^|[\n;{}]\s*)(?:(?:export|private|public|protected|static|async)\s+)*(\w+)\s*(?:<[^>]*>)?\s*\(/g;
  while ((m = method.exec(code))) {
    if (KEYWORDS.has(m[1])) continue;
    const open = m.index + m[0].length - 1;
    const close = matching(code, open);
    if (close < 0) continue;
    const after = code.slice(close + 1).match(/^\s*(?::\s*[^{;=]+?)?\s*\{/);
    if (after) add(m[1], close);
  }
  const arrow = /\b(?:const|let)\s+(\w+)\s*(?::[^=]+)?=\s*(?:async\s*)?\(/g;
  while ((m = arrow.exec(code))) {
    const open = m.index + m[0].length - 1;
    const close = matching(code, open);
    if (close < 0) continue;
    const after = code.slice(close + 1).match(/^\s*(?::\s*[^=]+?)?\s*=>\s*\{/);
    if (after) add(m[1], close);
  }
  return found;
}

/** The argument ranges of every guard call in the file. */
export function guardRanges(code) {
  const ranges = [];
  for (const name of GUARDS) {
    const re = new RegExp(`\\b${name}\\s*\\(`, 'g');
    let m;
    while ((m = re.exec(code))) {
      const open = m.index + m[0].length - 1;
      const close = matching(code, open);
      if (close > open) ranges.push([open, close]);
    }
  }
  return ranges;
}

/** Whether the name is one that this scan guards. */
export function isDestructive(name) {
  return DESTRUCTIVE_NAME.test(name) || EXTRA_NAMES.includes(name);
}

/**
 * Every unguarded call of a destructive function in *files* (`{ name, source }`).
 * `allow` maps `file::enclosing::callee` to a reason. Returns the violations and the
 * allowlist keys that were not needed.
 */
export function scan(files, allow = {}) {
  const used = new Set();
  const violations = [];
  const blanked = new Map(files.map((f) => [f.name, blank(f.source)]));
  // The names this code defines, so that a name the platform owns is not mistaken for
  // one of ours.
  const defined = new Set(EXTRA_NAMES);
  for (const [file, code] of blanked) {
    for (const f of functionsOf(code)) if (isDestructive(f.name)) defined.add(f.name);
    if (file === 'api.ts') {
      for (const m of code.matchAll(/export\s+(?:async\s+)?function\s+(\w+)/g)) {
        if (isDestructive(m[1])) defined.add(m[1]);
      }
    }
  }
  for (const { name: file, source } of files) {
    // The api module defines the calls. Its callers are what this scan checks.
    if (file === 'api.ts' || TYPE_ONLY.includes(file)) continue;
    const code = blanked.get(file);
    const fns = functionsOf(code);
    const guards = guardRanges(code);
    const re = /\b([A-Za-z_]\w*)\b/g;
    let m;
    while ((m = re.exec(code))) {
      const callee = m[1];
      if (!isDestructive(callee) || !defined.has(callee)) continue;
      const at = m.index;
      const dot = /\b(\w+)\s*\.\s*$/.exec(code.slice(Math.max(0, at - 40), at));
      if (dot && !RECEIVERS.includes(dot[1])) continue;
      // Only a call: the name is followed by "(" and is not a definition.
      if (!/^\s*\(/.test(code.slice(at + callee.length, at + callee.length + 12))) continue;
      const before = code.slice(Math.max(0, at - 40), at);
      if (/\bfunction\s+$/.test(before)) continue;
      const open = code.indexOf('(', at + callee.length);
      const close = matching(code, open);
      const after = close > 0 ? code.slice(close + 1, close + 160) : '';
      if (/^\s*(?::\s*[^{;=]+?)?\s*\{/.test(after) && /(^|[\n;{}]\s*)(?:(?:export|private|public|protected|static|async)\s+)*$/.test(before)) continue;
      if (guards.some(([from, to]) => at > from && at < to)) continue;
      const enclosing = fns
        .filter((f) => at > f.start && at < f.end)
        .sort((a, b) => b.start - a.start);
      if (enclosing.some((f) => isDestructive(f.name))) continue;
      const where = enclosing.length ? enclosing[0].name : '(top level)';
      const key = `${file}::${where}::${callee}`;
      if (key in allow) {
        used.add(key);
        continue;
      }
      const line = source.slice(0, at).split('\n').length;
      violations.push({ key, file, line, callee, where });
    }
  }
  const stale = Object.keys(allow).filter((k) => !used.has(k));
  return { violations, stale };
}
