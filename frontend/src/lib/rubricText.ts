// A rubric written as an outline, so it can be pasted from a document:
//
//   Short answer (5 points)
//   Analysis
//     Load the data
//     Fit the model (2 points)
//
// A line at the left margin starts a part; an indented line is an item of the
// part above it. Items are worth 1 point unless they end in "(N points)". A part
// with no items is scored as one item. Numbering ("3.", "a)") and a trailing
// "17/17" are dropped. Keys come from position ("3.4"), so a grader's scores
// stay with their items as long as the outline keeps its order.

import type { RubricSpec } from './api';

const NUMBERING = /^(?:\d+|[a-z]|[ivx]+)[.)]\s+/i;
const POINTS = /\s*\((\d+(?:\.\d+)?)\s*(?:points?|pts?)\)\s*$/i;
const TALLY = /\s+\d+(?:\.\d+)?\s*\/\s*\d+(?:\.\d+)?\s*$/;

function clean(line: string): { label: string; points: number | null } {
  let label = line.trim().replace(NUMBERING, '');
  let points: number | null = null;
  const m = label.match(POINTS);
  if (m) {
    points = Number(m[1]);
    label = label.slice(0, m.index).trim();
  }
  label = label.replace(TALLY, '').replace(/\s*[-–—:]\s*$/, '').trim();
  return { label, points };
}

export function parseRubric(text: string): { items: RubricSpec[]; errors: string[] } {
  const parts: { label: string; points: number | null; items: { label: string; points: number }[] }[] = [];
  const errors: string[] = [];
  text.split(/\r?\n/).forEach((raw, i) => {
    if (!raw.trim()) return;
    const { label, points } = clean(raw);
    if (!label) {
      errors.push(`Line ${i + 1} has no text.`);
    } else if (/^\s/.test(raw)) {
      const part = parts[parts.length - 1];
      if (part) part.items.push({ label, points: points ?? 1 });
      else errors.push(`Line ${i + 1} is indented but has no part above it.`);
    } else {
      parts.push({ label, points, items: [] });
    }
  });
  const items: RubricSpec[] = [];
  parts.forEach((p, i) => {
    if (p.items.length === 0) {
      items.push({ key: `${i + 1}`, label: p.label, points: p.points ?? 1, group: p.label });
    } else {
      p.items.forEach((it, j) => items.push({ key: `${i + 1}.${j + 1}`, label: it.label, points: it.points, group: p.label }));
    }
  });
  for (const it of items) if (!(it.points > 0)) errors.push(`"${it.label}" needs more than 0 points.`);
  return { items, errors };
}

export function formatRubric(items: RubricSpec[]): string {
  const lines: string[] = [];
  let group: string | undefined;
  for (const it of items) {
    const pts = `(${it.points} ${it.points === 1 ? 'point' : 'points'})`;
    if (!it.key.includes('.')) {
      lines.push(`${it.label} ${pts}`);
      group = undefined;
      continue;
    }
    if (it.group !== group) {
      lines.push(it.group ?? 'Items');
      group = it.group;
    }
    lines.push(`    ${it.label}${it.points === 1 ? '' : ` ${pts}`}`);
  }
  return lines.join('\n');
}

/** Items in order, gathered under their part, with each part's total. */
export function groupRubric<T extends { key: string; group?: string; max_points?: number; points?: number }>(
  items: T[],
): { label: string | null; total: number; items: T[] }[] {
  const out: { label: string | null; total: number; items: T[] }[] = [];
  for (const it of items) {
    const label = it.group ?? null;
    let g = out[out.length - 1];
    if (!g || g.label !== label) out.push((g = { label, total: 0, items: [] }));
    g.items.push(it);
    g.total += it.max_points ?? it.points ?? 0;
  }
  return out;
}
