import type { GradePolicy, Submission } from './api';

const dateFmt = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});

const dateOnlyFmt = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
});

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateFmt.format(d);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateOnlyFmt.format(d);
}

export function fmtRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.round((now - t) / 1000);
  const abs = Math.abs(s);
  const suffix = s >= 0 ? 'ago' : 'from now';
  if (abs < 60) return `${abs}s ${suffix}`;
  if (abs < 3600) return `${Math.round(abs / 60)}m ${suffix}`;
  if (abs < 86400) return `${Math.round(abs / 3600)}h ${suffix}`;
  return `${Math.round(abs / 86400)}d ${suffix}`;
}

export function fmtPoints(points: number | null | undefined, max?: number | null): string {
  if (points === null || points === undefined) return max != null ? `— / ${trim(max)}` : '—';
  return max != null ? `${trim(points)} / ${trim(max)}` : trim(points);
}

export function trim(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, '');
}

export function fmtPercent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

export function fmtPolicy(p: GradePolicy | undefined): string {
  switch (p) {
    case 'latest':
      return 'latest attempt';
    case 'highest':
      return 'highest attempt';
    case 'first':
      return 'first attempt';
    case 'selected':
      return 'student-selected attempt';
    default:
      return '—';
  }
}

export function submissionPoints(s: Submission): number | null {
  const sc = s.score;
  if (!sc) return null;
  if (sc.points !== null && sc.points !== undefined) return sc.points;
  const auto = sc.auto_points ?? 0;
  const manual = sc.manual_points ?? 0;
  if (sc.auto_points == null && sc.manual_points == null) return null;
  return auto + manual;
}

/** Pick the attempt that counts for a question under the offering's policy. */
export function countingAttempt(attempts: Submission[], policy: GradePolicy): Submission | null {
  if (attempts.length === 0) return null;
  const sorted = [...attempts].sort((a, b) => a.attempt_no - b.attempt_no);
  switch (policy) {
    case 'first':
      return sorted[0] ?? null;
    case 'highest': {
      let best: Submission | null = null;
      let bestPts = -Infinity;
      for (const s of sorted) {
        const p = submissionPoints(s);
        if (p !== null && p > bestPts) {
          best = s;
          bestPts = p;
        }
      }
      return best ?? sorted[sorted.length - 1] ?? null;
    }
    case 'selected':
      return sorted.find((s) => s.selected) ?? sorted[sorted.length - 1] ?? null;
    case 'latest':
    default:
      return sorted[sorted.length - 1] ?? null;
  }
}

export function statusLabel(s: Submission['status']): string {
  switch (s) {
    case 'received':
      return 'received';
    case 'checking':
      return 'checking';
    case 'awaiting_manual':
      return 'awaiting grading';
    case 'graded':
      return 'graded';
    case 'failed':
      return 'grader failed';
    default:
      return s;
  }
}
