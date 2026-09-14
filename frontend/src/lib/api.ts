// Typed client for the grader API (docs/api.md, contract v1).
//
// Browser callers authenticate with the HttpOnly `grader_session` cookie; every
// mutating request also carries `X-CSRF-Token`, fetched lazily from
// GET /auth/csrf and refreshed once if the server rejects it. Nothing is stored
// in localStorage. Endpoints that the notebook client calls with a Bearer token
// are typed here too (pass `token`) so the contract is covered end to end.

export const API_BASE = '/api/v1';

// ---------------------------------------------------------------------------
// Contract types
// ---------------------------------------------------------------------------

export type Role = 'student' | 'ta' | 'instructor';
export type GradePolicy = 'latest' | 'highest' | 'first' | 'selected';
export type Environment = 'molab' | 'wasm' | 'discovery';
export type GradingMode = 'auto' | 'manual' | 'hybrid';
export type CellState = 'none' | 'checking' | 'submitted' | 'graded';
export type SubmissionStatus =
  | 'received'
  | 'checking'
  | 'awaiting_manual'
  | 'graded'
  | 'failed';

export interface Health {
  ok: boolean;
  env: string;
  auth_mode: 'saml' | 'dev' | 'disabled';
  submissions_enabled: boolean;
  email_login_enabled: boolean;
}

export interface ErrorEnvelope {
  error: { code: string; message: string };
}

export interface Enrollment {
  offering_id: string;
  course_slug: string;
  term: string;
  title: string;
  role: Role;
}

export interface Me {
  netid: string;
  display_name: string;
  platform_admin: boolean;
  enrollments: Enrollment[];
}

export interface CsrfResponse {
  csrf_token: string;
}

export interface OfferingSettings {
  public_student_notebooks?: boolean;
  retention_days?: number;
  [key: string]: unknown;
}

export interface Section {
  id: string;
  name: string;
  ta_netids?: string[];
}

export interface Offering extends Enrollment {
  settings?: OfferingSettings;
  sections?: Section[];
}

export interface AssignmentSettings {
  due_at: string | null;
  attempts_allowed: number | null;
  grade_policy: GradePolicy;
  environments: Environment[];
  log_checks: boolean;
}

/** Server shape of GET /offerings/{id}/queue. */
interface RawQueue {
  question: {
    id: string;
    qid: string;
    title: string;
    max_points: number;
    auto_points_max: number;
    grading_mode: GradingMode;
    rubric: { id: string; name: string; items: { key: string; label?: string; points: number; description?: string }[] } | null;
  };
  items: Submission[];
}

export interface Queue {
  question: {
    id: string;
    qid: string;
    title: string;
    max_points: number;
    auto_points_max: number;
    grading_mode: GradingMode;
    rubric?: RubricItem[];
  };
  items: Submission[];
}

export interface RubricItem {
  key: string;
  title: string;
  max_points: number;
  description?: string;
}

export interface Question {
  id: string;
  qid: string;
  title: string;
  max_points: number;
  grading_mode: GradingMode;
  order: number;
  rubric?: RubricItem[];
}

export interface Assignment {
  id: string;
  slug: string;
  title: string;
  latest_version: number | null;
  settings: AssignmentSettings;
  questions: Question[];
}

export interface AssignmentCreate {
  slug: string;
  title: string;
  settings: Partial<AssignmentSettings>;
}

export interface AssignmentPatch {
  title?: string;
  settings?: Partial<AssignmentSettings>;
}

export interface QuestionSpec {
  qid: string;
  title: string;
  max_points: number;
  grading_mode: GradingMode;
  check_keys: string[];
  rubric?: RubricItem[];
}

export interface VersionUpload {
  instructor_notebook: File;
  student_notebook: File;
  questions: QuestionSpec[];
  cell_hashes: Record<string, string>;
}

export interface VersionResponse {
  version: number;
  student_url: string;
}

export interface Score {
  points: number | null;
  auto_points?: number | null;
  manual_points?: number | null;
  rubric_scores?: Record<string, number>;
  feedback?: string | null;
  final?: boolean;
  graded_at?: string | null;
  graded_by?: string | null;
}

export interface SubmissionClient {
  package: string;
  version: string;
  env: Environment | string;
}

export interface Submission {
  id: string;
  netid: string;
  display_name?: string;
  assignment_id?: string;
  assignment_version_id: string;
  assignment_slug?: string;
  assignment_title?: string;
  question_id: string;
  qid?: string;
  question_title?: string;
  max_points?: number;
  attempt_no: number;
  submitted_at: string;
  status: SubmissionStatus;
  score?: Score | null;
  feedback?: string | null;
  render_url?: string | null;
  /** Structured answers sent with the attempt (e.g. text-area values). */
  outputs?: Record<string, unknown>;
  selected?: boolean;
  error?: string | null;
  client?: SubmissionClient;
  rubric?: RubricItem[];
}

export interface SubmissionCreate {
  assignment_version_id: string;
  question_id: string;
  notebook: string;
  check_results: unknown[];
  outputs: Record<string, unknown>;
  client: SubmissionClient;
}

export interface SubmissionCreated {
  id: string;
  attempt_no: number;
  submitted_at: string;
  status: 'received';
}

export interface CheckEvent {
  assignment_version_id: string;
  question_id: string;
  check_key: string;
  passed: boolean;
}

export interface AwaitingManual {
  question_id: string;
  qid: string;
  title?: string;
  assignment_title?: string;
  count: number;
  oldest_submitted_at: string | null;
}

export interface InactiveStudent {
  netid: string;
  display_name?: string;
  section?: string | null;
  last_activity: string | null;
}

export interface FailingCheck {
  qid: string;
  question_id?: string;
  check_key: string;
  fail_rate: number;
  n: number;
  message?: string | null;
}

export interface GraderFailure {
  submission_id: string;
  question_id: string;
  qid?: string;
  netid: string;
  error?: string | null;
  submitted_at?: string;
}

export interface Triage {
  awaiting_manual: AwaitingManual[];
  inactive_students: InactiveStudent[];
  failing_checks: FailingCheck[];
  grader_failures: GraderFailure[];
}

export interface GridCell {
  state: CellState;
  points: number | null;
  max: number;
  attempts?: number;
}

export interface GridStudent {
  netid: string;
  display_name: string;
  section: string | null;
  last_activity: string | null;
  cells: Record<string, GridCell>;
}

export interface Grid {
  students: GridStudent[];
}

export interface ScoreInput {
  manual_points: number | null;
  rubric_scores: Record<string, number>;
  feedback: string;
  final: boolean;
}

export interface StudentHistory {
  netid: string;
  display_name: string;
  section?: string | null;
  submissions: Submission[];
}

export type RosterSource = 'canvas_csv' | 'banner';

export interface RosterRow {
  netid: string;
  display_name: string;
  section: string | null;
}

export interface RosterMove extends RosterRow {
  from_section?: string | null;
}

export interface RosterPreview {
  adds: RosterRow[];
  drops: RosterRow[];
  moves: RosterMove[];
  unmatched: RosterRow[];
}

export interface RosterApplied {
  added: number;
  dropped: number;
  moved: number;
  [key: string]: unknown;
}

export interface AuditEntry {
  id: string;
  at: string;
  actor: string | null;
  offering?: string | null;
  entity: string;
  entity_id: string;
  action: string;
  before: Record<string, any> | null;
  after: Record<string, any> | null;
  reason: string | null;
}

export interface StaffAdd {
  netid: string;
  role: 'ta' | 'instructor';
  ta_sections?: string[];
  display_name?: string;
}

export interface RosterEnrollment extends RosterRow {
  role: Role;
  active?: boolean;
}

export interface Course {
  id: string;
  slug: string;
  title: string;
  offerings?: AdminOffering[];
}

export interface CourseCreate {
  slug: string;
  title: string;
}

export interface AdminOffering {
  id: string;
  course_id: string;
  term: string;
  title: string;
  settings?: OfferingSettings;
  instructors?: string[];
}

export interface OfferingCreate {
  term: string;
  title: string;
  settings?: OfferingSettings;
}

export interface InstructorAdd {
  netid: string;
}

export interface DeviceStart {
  device_code: string;
  user_code: string;
  verification_url: string;
  expires_in: number;
  interval: number;
}

export type DeviceToken =
  | { status: 'pending' }
  | { status: 'expired' }
  | {
      status: 'approved';
      access_token: string;
      token_type: 'bearer';
      expires_in: number;
      netid: string;
    };

export type GraderEventType =
  | 'submission.received'
  | 'submission.graded'
  | 'score.updated';

export interface GraderEvent {
  type: GraderEventType;
  submission_id: string;
  question_id: string;
  netid: string;
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message || `${err.code} (${err.status})`;
  if (err instanceof Error) return err.message;
  return String(err);
}

async function toApiError(res: Response): Promise<ApiError> {
  const text = await res.text().catch(() => '');
  try {
    const body = JSON.parse(text) as Partial<ErrorEnvelope>;
    if (body && body.error && typeof body.error.code === 'string') {
      return new ApiError(res.status, body.error.code, body.error.message ?? '');
    }
  } catch {
    // not JSON
  }
  const fallback: Record<number, string> = {
    401: 'unauthenticated',
    403: 'forbidden',
    404: 'not_found',
    409: 'conflict',
    422: 'validation_error',
  };
  return new ApiError(
    res.status,
    fallback[res.status] ?? 'http_error',
    text.trim() || `${res.status} ${res.statusText}`,
  );
}

// ---------------------------------------------------------------------------
// CSRF
// ---------------------------------------------------------------------------

let csrfToken: string | null = null;
let csrfInflight: Promise<string> | null = null;

async function fetchCsrf(): Promise<string> {
  const res = await fetch(`${API_BASE}/auth/csrf`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) throw await toApiError(res);
  const body = (await res.json()) as CsrfResponse;
  csrfToken = body.csrf_token;
  return csrfToken;
}

async function getCsrf(force = false): Promise<string> {
  if (!force && csrfToken) return csrfToken;
  if (!csrfInflight) {
    csrfInflight = fetchCsrf().finally(() => {
      csrfInflight = null;
    });
  }
  return csrfInflight;
}

/** Forget the cached CSRF token (call after sign-out or on a new session). */
export function resetCsrf(): void {
  csrfToken = null;
}

// ---------------------------------------------------------------------------
// Request core
// ---------------------------------------------------------------------------

type Query = Record<string, string | number | boolean | null | undefined>;

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  query?: Query;
  body?: unknown;
  form?: FormData;
  token?: string;
  signal?: AbortSignal;
  redirect?: RequestRedirect;
  /** Skip the CSRF header. Only for routes that take no session at all. */
  anonymous?: boolean;
}

function qs(query?: Query): string {
  if (!query) return '';
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === '') continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : '';
}

function url(path: string, query?: Query): string {
  return `${API_BASE}${path}${qs(query)}`;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? 'GET';
  const mutating = method !== 'GET';
  const useCsrf = mutating && !opts.token && !opts.anonymous;

  const build = async (freshCsrf: boolean): Promise<Request> => {
    const headers = new Headers({ Accept: 'application/json' });
    if (opts.body !== undefined) headers.set('Content-Type', 'application/json');
    if (opts.token) headers.set('Authorization', `Bearer ${opts.token}`);
    if (useCsrf) headers.set('X-CSRF-Token', await getCsrf(freshCsrf));
    return new Request(url(path, opts.query), {
      method,
      headers,
      credentials: 'include',
      body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
      signal: opts.signal,
      redirect: opts.redirect ?? 'follow',
    });
  };

  let res = await fetch(await build(false));

  // A stale CSRF token (new session, rotated secret) comes back as 403. Refresh once.
  if (useCsrf && res.status === 403) {
    const err = await toApiError(res.clone());
    if (/csrf/i.test(err.code) || /csrf/i.test(err.message)) {
      res = await fetch(await build(true));
    }
  }

  if (res.type === 'opaqueredirect') return undefined as T;
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;

  const ct = res.headers.get('content-type') ?? '';
  if (ct.includes('application/json')) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export const api = {
  auth: {
    /** Browser navigation target that begins the SAML flow. */
    loginUrl(next = '/'): string {
      return url('/auth/login', { next });
    },
    /** Dev-mode only (GRADER_AUTH_MODE=dev). */
    devLoginUrl(netid: string, next = '/'): string {
      return url('/auth/dev-login', { netid, next });
    },
    metadataUrl(): string {
      return url('/auth/saml/metadata');
    },
    /**
     * Ask for a one-time sign-in link by email. Unauthenticated, and the answer
     * is deliberately the same whether or not the address is enrolled, so the
     * caller can only ever report "if it exists, it has been sent".
     */
    emailLogin(email: string, next?: string): Promise<{ ok: boolean; message: string }> {
      return request('/auth/email-login', {
        method: 'POST',
        body: { email, next },
        anonymous: true,
      });
    },
    me(signal?: AbortSignal): Promise<Me> {
      return request<Me>('/auth/me', { signal });
    },
    csrf(): Promise<string> {
      return getCsrf(true);
    },
    /**
     * Clears the session cookie. The server answers with a 302 (to the campus
     * logout page in production); fetch cannot follow that navigation, so the
     * caller is responsible for moving the browser afterwards.
     */
    async logout(): Promise<void> {
      await request<void>('/auth/logout', { method: 'POST', redirect: 'manual' });
      resetCsrf();
    },
  },

  device: {
    start(client: string): Promise<DeviceStart> {
      return request<DeviceStart>('/auth/device', { method: 'POST', body: { client } });
    },
    verifyUrl(code: string): string {
      return url('/auth/device/verify', { code });
    },
    token(device_code: string): Promise<DeviceToken> {
      return request<DeviceToken>('/auth/device/token', {
        method: 'POST',
        body: { device_code },
      });
    },
  },

  offerings: {
    list(signal?: AbortSignal): Promise<Offering[]> {
      return request<Offering[]>('/offerings', { signal });
    },
    get(offeringId: string, signal?: AbortSignal): Promise<Offering> {
      return request<Offering>(`/offerings/${enc(offeringId)}`, { signal });
    },
    assignments(offeringId: string, signal?: AbortSignal): Promise<Assignment[]> {
      return request<Assignment[]>(`/offerings/${enc(offeringId)}/assignments`, { signal });
    },
  },

  assignments: {
    create(offeringId: string, body: AssignmentCreate): Promise<Assignment> {
      return request<Assignment>(`/offerings/${enc(offeringId)}/assignments`, {
        method: 'POST',
        body,
      });
    },
    patch(offeringId: string, assignmentId: string, body: AssignmentPatch): Promise<Assignment> {
      return request<Assignment>(
        `/offerings/${enc(offeringId)}/assignments/${enc(assignmentId)}`,
        { method: 'PATCH', body },
      );
    },
    uploadVersion(
      offeringId: string,
      assignmentId: string,
      upload: VersionUpload,
    ): Promise<VersionResponse> {
      const form = new FormData();
      form.set('instructor_notebook', upload.instructor_notebook);
      form.set('student_notebook', upload.student_notebook);
      form.set('questions', JSON.stringify(upload.questions));
      form.set('cell_hashes', JSON.stringify(upload.cell_hashes));
      return request<VersionResponse>(
        `/offerings/${enc(offeringId)}/assignments/${enc(assignmentId)}/versions`,
        { method: 'POST', form },
      );
    },
    studentNotebookUrl(versionId: string): string {
      return url(`/assignment-versions/${enc(versionId)}/student.py`);
    },
    studentNotebook(versionId: string): Promise<string> {
      return request<string>(`/assignment-versions/${enc(versionId)}/student.py`);
    },
  },

  submissions: {
    /** Notebook client only: requires a Bearer token from the device handshake. */
    create(body: SubmissionCreate, token: string): Promise<SubmissionCreated> {
      return request<SubmissionCreated>('/submissions', { method: 'POST', body, token });
    },
    get(submissionId: string, signal?: AbortSignal): Promise<Submission> {
      return request<Submission>(`/submissions/${enc(submissionId)}`, { signal });
    },
    mine(offeringId: string, assignmentId?: string, signal?: AbortSignal): Promise<Submission[]> {
      return request<Submission[]>(`/offerings/${enc(offeringId)}/me/submissions`, {
        query: { assignment_id: assignmentId },
        signal,
      });
    },
    /** Notebook client only. */
    checkEvent(body: CheckEvent, token: string): Promise<void> {
      return request<void>('/check-events', { method: 'POST', body, token });
    },
  },

  grading: {
    triage(offeringId: string, signal?: AbortSignal): Promise<Triage> {
      return request<Triage>(`/offerings/${enc(offeringId)}/triage`, { signal });
    },
    grid(offeringId: string, assignmentId?: string, signal?: AbortSignal): Promise<Grid> {
      return request<Grid>(`/offerings/${enc(offeringId)}/grid`, {
        query: { assignment_id: assignmentId },
        signal,
      });
    },
    async queue(offeringId: string, questionId: string, signal?: AbortSignal): Promise<Queue> {
      const raw = await request<RawQueue>(`/offerings/${enc(offeringId)}/queue`, {
        query: { question_id: questionId },
        signal,
      });
      const rubric: RubricItem[] | undefined = raw.question.rubric?.items.map((r) => ({
        key: r.key,
        title: r.label ?? r.key,
        max_points: r.points,
        description: r.description,
      }));
      return { question: { ...raw.question, rubric }, items: raw.items };
    },
    score(submissionId: string, body: ScoreInput): Promise<Score> {
      return request<Score>(`/submissions/${enc(submissionId)}/score`, {
        method: 'POST',
        body,
      });
    },
    audit(offeringId: string, signal?: AbortSignal): Promise<AuditEntry[]> {
      return request<AuditEntry[]>(`/offerings/${enc(offeringId)}/audit`, { signal });
    },
    retry(submissionId: string): Promise<{ id: string; status: string }> {
      return request(`/submissions/${enc(submissionId)}/retry`, { method: 'POST' });
    },
    student(offeringId: string, netid: string, signal?: AbortSignal): Promise<StudentHistory> {
      return request<StudentHistory>(
        `/offerings/${enc(offeringId)}/students/${enc(netid)}`,
        { signal },
      );
    },
  },

  roster: {
    preview(offeringId: string, file: File, source: RosterSource): Promise<RosterPreview> {
      const form = new FormData();
      form.set('file', file);
      form.set('source', source);
      return request<RosterPreview>(`/offerings/${enc(offeringId)}/roster/preview`, {
        method: 'POST',
        form,
      });
    },
    apply(offeringId: string, payload: RosterPreview): Promise<RosterApplied> {
      return request<RosterApplied>(`/offerings/${enc(offeringId)}/roster/apply`, {
        method: 'POST',
        body: payload,
      });
    },
    list(offeringId: string, signal?: AbortSignal): Promise<RosterEnrollment[]> {
      return request<RosterEnrollment[]>(`/offerings/${enc(offeringId)}/roster`, { signal });
    },
    addStaff(offeringId: string, body: StaffAdd): Promise<{ netid: string; role: string }> {
      return request(`/offerings/${enc(offeringId)}/roster/staff`, { method: 'POST', body });
    },
    /** Add or reinstate one student. Import stays the bulk path. */
    addStudent(
      offeringId: string,
      body: { netid: string; display_name?: string; section?: string },
    ): Promise<{ netid: string; role: string; status: string }> {
      return request(`/offerings/${enc(offeringId)}/roster/students`, { method: 'POST', body });
    },
    /** Soft drop: the enrollment row survives, because submissions reference it. */
    drop(offeringId: string, netid: string): Promise<{ netid: string; status: string }> {
      return request(`/offerings/${enc(offeringId)}/roster/${enc(netid)}`, { method: 'DELETE' });
    },
  },

  exports: {
    /** Direct download link; the browser sends the session cookie. */
    canvasUrl(offeringId: string, assignmentIds: string[]): string {
      return url(`/offerings/${enc(offeringId)}/export/canvas`, {
        assignment_ids: assignmentIds.join(','),
      });
    },
  },

  admin: {
    courses(signal?: AbortSignal): Promise<Course[]> {
      return request<Course[]>('/admin/courses', { signal });
    },
    audit(signal?: AbortSignal): Promise<AuditEntry[]> {
      return request<AuditEntry[]>('/admin/audit', { signal });
    },
    createCourse(body: CourseCreate): Promise<Course> {
      return request<Course>('/admin/courses', { method: 'POST', body });
    },
    createOffering(courseId: string, body: OfferingCreate): Promise<AdminOffering> {
      return request<AdminOffering>(`/admin/courses/${enc(courseId)}/offerings`, {
        method: 'POST',
        body,
      });
    },
    addInstructor(offeringId: string, body: InstructorAdd): Promise<void> {
      return request<void>(`/admin/offerings/${enc(offeringId)}/instructors`, {
        method: 'POST',
        body,
      });
    },
  },

  /** Service status. Lives outside /api/v1 and needs no session. */
  async health(signal?: AbortSignal): Promise<Health> {
    const res = await fetch('/api/health', { headers: { Accept: 'application/json' }, signal });
    if (!res.ok) throw new ApiError(res.status, 'unavailable', 'health check failed');
    return (await res.json()) as Health;
  },

  events: {
    url(offeringId: string): string {
      return url(`/offerings/${enc(offeringId)}/events`);
    },
  },
};

function enc(segment: string): string {
  return encodeURIComponent(segment);
}
