import type { Page } from '@playwright/test';

/**
 * An audit of painted outlines (#554).
 *
 * A control with a border, a ring or an outline must show all of it. Two faults hide an
 * outline, and neither shows in the computed style of the control alone:
 *
 *  - **clipped**: an ancestor with `overflow: hidden` (or `clip`) cuts the outline. Either
 *    a side of the control lies outside the clip box, or a square corner of the control
 *    lies outside the rounded corner of the clip box. A selected segment of a pill group
 *    was cut this way: its square box and inset ring sat under the round end of the group.
 *  - **open**: the control has a border on most sides, and on another side the border
 *    has width but a transparent colour, so the outline has a gap there. A list row with
 *    no status was open on its left side.
 *
 * The audit walks every element of the panel and the card, shadow roots included. It
 * reads layout and computed style only: it has no timing and no pixels, so it does not
 * flake. Run it on each captured view at each width (`outline-audit.spec.ts`).
 *
 * What it cannot see: a control that is clipped by a scroller (`overflow: auto`, or a hidden
 * box whose content is longer than the box), because a scrolled-off control is meant to be cut; an outline drawn by an image or a
 * `background` gradient; an outline cut by the viewport; and a clip by `clip-path`.
 * A control that is cut on purpose carries `data-hk-cut` on it or on an ancestor.
 */
export type OutlineFinding = string;

export async function auditOutlines(page: Page): Promise<OutlineFinding[]> {
  // Fonts change the width of a label and so the size of a pill. Two frames let a Lit
  // element finish its first paint.
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
  });
  return page.evaluate(() => {
    const out = new Set<string>();
    const EDGE = 0.75; // px of slack for sub-pixel layout
    const px = (v: string): number => parseFloat(v) || 0;
    const alpha = (c: string): number => {
      const m = c.match(/rgba?\(([^)]+)\)/) || c.match(/color\(srgb ([^)]+)\)/);
      if (!m) return c === 'transparent' ? 0 : 1;
      const parts = m[1].split(/[ ,/]+/).filter(Boolean);
      return parts.length >= 4 ? parseFloat(parts[3]) : 1;
    };
    const flatParent = (el: Element): Element | null => {
      if ((el as HTMLElement).assignedSlot) return (el as HTMLElement).assignedSlot;
      if (el.parentElement) return el.parentElement;
      const root = el.getRootNode();
      return root instanceof ShadowRoot ? root.host : null;
    };
    const isOurs = (el: Element): boolean => {
      for (let p: Element | null = el; p; p = flatParent(p)) {
        const tag = p.tagName.toLowerCase();
        if (tag === 'home-keeper-panel' || tag === 'home-keeper-card') return true;
      }
      return false;
    };
    const cutOnPurpose = (el: Element): boolean => {
      for (let p: Element | null = el; p; p = flatParent(p)) {
        if (p.hasAttribute('data-hk-cut')) return true;
      }
      return false;
    };
    const describe = (el: Element): string => {
      const r = el.getBoundingClientRect();
      const cls = (el.getAttribute('class') || '').trim().split(/\s+/).slice(0, 3).join('.');
      const text = ((el as HTMLElement).innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 18);
      return `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}${text ? ` "${text}"` : ''} ${Math.round(r.width)}x${Math.round(r.height)}`;
    };
    /** Split a computed box-shadow into its layers (commas inside rgb() do not split). */
    const layers = (v: string): string[] => {
      if (!v || v === 'none') return [];
      const parts: string[] = [];
      let depth = 0;
      let cur = '';
      for (const ch of v) {
        if (ch === '(') depth++;
        if (ch === ')') depth--;
        if (ch === ',' && depth === 0) {
          parts.push(cur.trim());
          cur = '';
        } else cur += ch;
      }
      if (cur.trim()) parts.push(cur.trim());
      return parts;
    };
    /** A shadow layer that draws a ring: no blur, and a spread, or an inset edge. */
    const hasRing = (cs: CSSStyleDeclaration): boolean =>
      layers(cs.boxShadow).some((l) => {
        const color = l.match(/(rgba?\([^)]*\)|color\([^)]*\))/)?.[0] || '';
        if (alpha(color) < 0.05) return false;
        const nums = l
          .replace(color, '')
          .replace('inset', '')
          .trim()
          .split(/\s+/)
          .map((n) => parseFloat(n));
        const [x = 0, y = 0, blur = 0, spread = 0] = nums;
        return blur === 0 && (spread >= 0.5 || (l.includes('inset') && (Math.abs(x) >= 0.5 || Math.abs(y) >= 0.5)));
      });

    type Side = 'top' | 'right' | 'bottom' | 'left';
    const SIDES: Side[] = ['top', 'right', 'bottom', 'left'];

    const walk = (root: ParentNode, fn: (el: Element) => void): void => {
      root.querySelectorAll('*').forEach((el) => {
        fn(el);
        if (el.shadowRoot) walk(el.shadowRoot, fn);
      });
    };

    walk(document, (el) => {
      if (!isOurs(el) || cutOnPurpose(el)) return;
      const r = el.getBoundingClientRect();
      if (r.width < 6 || r.height < 6) return;
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility !== 'visible' || px(cs.opacity) === 0) return;

      // Which sides paint a line?
      const painted: Record<Side, boolean> = { top: false, right: false, bottom: false, left: false };
      const gap: Side[] = [];
      for (const s of SIDES) {
        const w = px(cs.getPropertyValue(`border-${s}-width`));
        const style = cs.getPropertyValue(`border-${s}-style`);
        const a = alpha(cs.getPropertyValue(`border-${s}-color`));
        if (w >= 0.5 && style !== 'none' && style !== 'hidden') {
          if (a >= 0.05) painted[s] = true;
          else gap.push(s);
        }
      }
      const ring = hasRing(cs);
      const outline = cs.outlineStyle !== 'none' && px(cs.outlineWidth) >= 0.5 && alpha(cs.outlineColor) >= 0.05;
      const anyBorder = SIDES.some((s) => painted[s]);
      if (!anyBorder && !ring && !outline) return;
      // A ring or an outline draws on all sides.
      if (ring || outline) SIDES.forEach((s) => (painted[s] = true));

      // Open: a border with a gap on one side.
      // A seam (1 painted side, and the other sides transparent) is a divider, not an outline.
      if (anyBorder && gap.length > 0 && SIDES.filter((s) => painted[s]).length > gap.length) {
        out.add(`open: ${describe(el)} has a transparent ${gap.join(', ')} border`);
      }

      // Clipped: an ancestor that hides its overflow.
      const radii = {
        tl: px(cs.borderTopLeftRadius),
        tr: px(cs.borderTopRightRadius),
        br: px(cs.borderBottomRightRadius),
        bl: px(cs.borderBottomLeftRadius),
      };
      for (let a = flatParent(el); a; a = flatParent(a)) {
        // Home Assistant locks the page (`overflow: hidden` on body) while a dialog is open.
        // The page is the window, so a control below the fold is scrolled off, not cut.
        if (a === document.body || a === document.documentElement) continue;
        const ac = getComputedStyle(a);
        const hides = (v: string): boolean => v === 'hidden' || v === 'clip';
        if (!hides(ac.overflowX) && !hides(ac.overflowY)) continue;
        const ar = a.getBoundingClientRect();
        const bw = {
          top: px(ac.borderTopWidth),
          right: px(ac.borderRightWidth),
          bottom: px(ac.borderBottomWidth),
          left: px(ac.borderLeftWidth),
        };
        const box = {
          left: ar.left + bw.left,
          top: ar.top + bw.top,
          right: ar.right - bw.right,
          bottom: ar.bottom - bw.bottom,
        };
        // A box whose content is longer than the box (`scrollHeight` over `clientHeight`) is a
        // scroller that a script or a dialog drives. Its content is cut as it scrolls, by design.
        const ael = a as HTMLElement;
        const scrollsX = ael.scrollWidth > ael.clientWidth + 1;
        const scrollsY = ael.scrollHeight > ael.clientHeight + 1;
        const edge = {
          left: r.left < box.left - EDGE && hides(ac.overflowX) && !scrollsX,
          right: r.right > box.right + EDGE && hides(ac.overflowX) && !scrollsX,
          top: r.top < box.top - EDGE && hides(ac.overflowY) && !scrollsY,
          bottom: r.bottom > box.bottom + EDGE && hides(ac.overflowY) && !scrollsY,
        };
        // The control is outside the clip box on this side: it is cut, or it is hidden.
        // Only a control that is mostly inside is "cut"; one far outside is scrolled or
        // positioned away on purpose.
        const inside = r.right > box.left && r.left < box.right && r.bottom > box.top && r.top < box.bottom;
        if (inside) {
          for (const s of SIDES) {
            if (edge[s] && painted[s]) {
              out.add(`clipped: ${describe(el)} ${s} edge is cut by ${describe(a)}`);
            }
          }
        }
        // Corners: is the square corner of the control outside the round corner of the clip?
        const inner = {
          tl: Math.max(0, px(ac.borderTopLeftRadius) - Math.max(bw.top, bw.left)),
          tr: Math.max(0, px(ac.borderTopRightRadius) - Math.max(bw.top, bw.right)),
          br: Math.max(0, px(ac.borderBottomRightRadius) - Math.max(bw.bottom, bw.right)),
          bl: Math.max(0, px(ac.borderBottomLeftRadius) - Math.max(bw.bottom, bw.left)),
        };
        // The radii of a box are scaled down together when they do not fit.
        const bwid = box.right - box.left;
        const bhei = box.bottom - box.top;
        const f = Math.min(
          1,
          inner.tl + inner.tr > 0 ? bwid / (inner.tl + inner.tr) : 1,
          inner.bl + inner.br > 0 ? bwid / (inner.bl + inner.br) : 1,
          inner.tl + inner.bl > 0 ? bhei / (inner.tl + inner.bl) : 1,
          inner.tr + inner.br > 0 ? bhei / (inner.tr + inner.br) : 1,
        );
        const corners: Array<[keyof typeof inner, number, number, 1 | -1, 1 | -1, Side, Side]> = [
          ['tl', r.left, r.top, 1, 1, 'top', 'left'],
          ['tr', r.right, r.top, -1, 1, 'top', 'right'],
          ['br', r.right, r.bottom, -1, -1, 'bottom', 'right'],
          ['bl', r.left, r.bottom, 1, -1, 'bottom', 'left'],
        ];
        for (const [k, cx, cy, dx, dy, s1, s2] of corners) {
          const rc = inner[k] * f;
          if (rc < 1) continue;
          if (!(painted[s1] || painted[s2])) continue;
          // The point of the control's own rounded corner that is nearest to the clip corner.
          const own = radii[k];
          const shift = own * (1 - Math.SQRT1_2);
          const px0 = cx + dx * shift;
          const py0 = cy + dy * shift;
          // The centre of the clip's corner arc.
          const ccx = dx === 1 ? box.left + rc : box.right - rc;
          const ccy = dy === 1 ? box.top + rc : box.bottom - rc;
          const inZone = dx === 1 ? px0 < ccx : px0 > ccx;
          const inZoneY = dy === 1 ? py0 < ccy : py0 > ccy;
          if (!inZone || !inZoneY) continue;
          if (!(cx >= box.left - EDGE && cx <= box.right + EDGE && cy >= box.top - EDGE && cy <= box.bottom + EDGE)) continue;
          const dist = Math.hypot(px0 - ccx, py0 - ccy);
          if (dist > rc + EDGE) {
            out.add(
              `clipped: ${describe(el)} ${k} corner (radius ${own}) is cut by the round end of ${describe(a)} (radius ${Math.round(rc)})`,
            );
          }
        }
      }
    });
    return Array.from(out).sort();
  });
}
