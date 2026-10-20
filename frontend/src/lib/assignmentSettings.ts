// The assignment settings form, shared by the list (new assignment) and the
// detail page (edit). Dates are edited as local datetime-local strings and
// stored as UTC ISO.

import type { AssignmentSettings, Environment, GradePolicy, Visibility } from './api';

export const ENVIRONMENTS: Environment[] = ['molab', 'wasm', 'discovery'];
export const POLICIES: GradePolicy[] = ['latest', 'highest', 'first', 'selected'];

export interface SettingsForm {
  visibility: Visibility;
  release_at: string;
  due_at: string;
  close_at: string;
  late_policy: 'accept' | 'reject';
  attempts_allowed: number | null;
  grade_policy: GradePolicy;
  environments: Environment[];
  log_checks: boolean;
  autograde: boolean;
  render: boolean;
  notebook_submission: boolean;
  notebook_points: number;
}

export function blankSettings(): SettingsForm {
  return {
    visibility: 'public',
    release_at: '',
    due_at: '',
    close_at: '',
    late_policy: 'accept',
    attempts_allowed: null,
    grade_policy: 'latest',
    environments: ['molab', 'wasm'],
    log_checks: true,
    autograde: true,
    render: true,
    notebook_submission: false,
    notebook_points: 0,
  };
}

export function toLocalInput(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const local = (iso: string | null | undefined) => (iso ? toLocalInput(iso) : '');
const utc = (value: string) => (value ? new Date(value).toISOString() : null);

export function toForm(s: AssignmentSettings): SettingsForm {
  return {
    visibility: s.visibility ?? 'public',
    release_at: local(s.release_at),
    due_at: local(s.due_at),
    close_at: local(s.close_at),
    late_policy: s.late_policy === 'reject' ? 'reject' : 'accept',
    attempts_allowed: s.attempts_allowed,
    grade_policy: s.grade_policy,
    environments: [...s.environments],
    log_checks: s.log_checks,
    autograde: s.autograde ?? true,
    render: s.render ?? true,
    notebook_submission: s.notebook_submission ?? false,
    notebook_points: s.notebook_points ?? 0,
  };
}

export function fromForm(f: SettingsForm): AssignmentSettings {
  // A private assignment with a deadline but no close would leave its data
  // readable forever; close it at the deadline unless told otherwise.
  const close = f.close_at || (f.visibility === 'enrolled' ? f.due_at : '');
  return {
    visibility: f.visibility,
    release_at: utc(f.release_at),
    due_at: utc(f.due_at),
    close_at: utc(close),
    late_policy: f.late_policy === 'reject' ? 'reject' : null,
    attempts_allowed: f.attempts_allowed === null || Number.isNaN(f.attempts_allowed) ? null : f.attempts_allowed,
    grade_policy: f.grade_policy,
    environments: f.environments,
    log_checks: f.log_checks,
    autograde: f.autograde,
    render: f.render,
    notebook_submission: f.notebook_submission,
    notebook_points: f.notebook_submission ? Number(f.notebook_points) || 0 : 0,
  };
}
