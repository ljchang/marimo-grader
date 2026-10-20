// How an assignment reads to its instructor, shared by the assignments table
// and the assignment page: the one date that matters now, the labels for what
// is unusual about it, and where its Grade button goes.

import { api, type Assignment, type AssignmentProgress, type Enrollment } from './api';
import { fmtDateTime } from './format';
import { auth } from './auth.svelte';
import { router } from './router.svelte';

export type Phase = 'open' | 'upcoming' | 'closed';

export const phase = (a: Assignment): Phase => a.availability?.state ?? 'open';

/** Private with no open date: students cannot see it at all yet. */
export const hidden = (a: Assignment) => a.settings.visibility === 'enrolled' && !a.settings.release_at;

const DAY = 86_400_000;

/** "in 5 days", "tomorrow", "in 3 hours", "2 days ago", from a timestamp. */
export function relative(iso: string, now = Date.now()): string {
  const ms = new Date(iso).getTime() - now;
  const abs = Math.abs(ms);
  const future = ms >= 0;
  if (abs < 3_600_000) {
    const m = Math.max(1, Math.round(abs / 60_000));
    return future ? `in ${m} min` : `${m} min ago`;
  }
  if (abs < DAY) {
    const h = Math.round(abs / 3_600_000);
    return future ? `in ${h} ${h === 1 ? 'hour' : 'hours'}` : `${h} ${h === 1 ? 'hour' : 'hours'} ago`;
  }
  const d = Math.round(abs / DAY);
  if (d === 1) return future ? 'tomorrow' : 'yesterday';
  return future ? `in ${d} days` : `${d} days ago`;
}

export interface When {
  text: string;
  detail: string;
  /** Due within two days: worth noticing. */
  soon: boolean;
  /** The timestamp the When column sorts by; null sorts last. */
  sortAt: number | null;
}

export function when(a: Assignment, now = Date.now()): When {
  const s = a.settings;
  const at = (iso: string | null | undefined) => (iso ? new Date(iso).getTime() : null);
  const late = s.late_policy === 'reject' ? 'No late work' : 'Late work accepted';
  switch (phase(a)) {
    case 'upcoming':
      if (!s.release_at) return { text: 'No open date', detail: 'Set one in Settings to release it', soon: false, sortAt: null };
      return { text: `Opens ${relative(s.release_at, now)}`, detail: fmtDateTime(s.release_at), soon: false, sortAt: at(s.release_at) };
    case 'closed':
      return { text: 'Closed', detail: fmtDateTime(s.close_at), soon: false, sortAt: at(s.close_at) };
    default: {
      if (!s.due_at) return { text: 'No due date', detail: late, soon: false, sortAt: null };
      const due = at(s.due_at)!;
      if (due < now) return { text: `Was due ${relative(s.due_at, now)}`, detail: s.close_at ? `Closes ${fmtDateTime(s.close_at)}` : late, soon: false, sortAt: due };
      return { text: `Due ${relative(s.due_at, now)}`, detail: fmtDateTime(s.due_at), soon: due - now < 2 * DAY, sortAt: due };
    }
  }
}

export interface Tag {
  label: string;
  title: string;
  warn?: boolean;
}

/** Only what is unusual about an assignment gets a label. */
export function tags(a: Assignment): Tag[] {
  const out: Tag[] = [];
  if (hidden(a)) out.push({ label: 'Hidden from students', title: 'No open date yet, so students cannot see it', warn: true });
  if (a.settings.visibility === 'enrolled') out.push({ label: 'Enrolled only', title: 'Only enrolled students can open it' });
  if (a.settings.render === false) out.push({ label: 'Not re-run', title: 'Submissions are not re-run; you read the code and the saved files' });
  return out;
}

export const points = (a: Assignment) => a.questions.reduce((n, q) => n + q.max_points, 0);

export function summary(a: Assignment): string {
  const n = a.questions.length;
  const pts = points(a);
  const only = n === 1 ? a.questions[0] : undefined;
  if (only?.qid === 'notebook') {
    return `${pts} points, whole notebook${a.settings.autograde === false || only.grading_mode !== 'auto' ? ' graded by hand' : ''}`;
  }
  return `${pts} ${pts === 1 ? 'point' : 'points'}, ${n} ${n === 1 ? 'question' : 'questions'}`;
}

export const uploadLabel = (a: Assignment) =>
  a.latest_version === null ? 'Upload instructor notebook…' : 'Upload corrected notebook…';

/** Where Grade goes: straight into the queue when only one question has answers waiting. */
export function gradeHref(offeringId: string, a: Assignment, p: AssignmentProgress | undefined): string {
  const waiting = Object.entries(p?.questions ?? {}).filter(([, q]) => q.counts.waiting > 0);
  const [only] = waiting;
  if (waiting.length === 1 && only) return `/o/${offeringId}/grade/${only[0]}`;
  return `/o/${offeringId}/assignments/${a.id}`;
}

export function studentLink(e: Enrollment | null, a: Assignment): string | null {
  if (!e) return null;
  return `${location.origin}/a/${e.course_slug}/${e.term}/${a.slug}/launch`;
}

export async function copyStudentLink(e: Enrollment | null, a: Assignment): Promise<string> {
  const link = studentLink(e, a);
  if (!link) throw new Error('No student link for this course.');
  await navigator.clipboard.writeText(link);
  return link;
}

export async function previewAsStudent(offeringId: string): Promise<void> {
  await auth.setPreview(offeringId, true);
  router.navigate(`/me/${offeringId}`);
}

export function exportCanvas(offeringId: string, ids: string[]): void {
  window.location.assign(api.exports.canvasUrl(offeringId, ids));
}
