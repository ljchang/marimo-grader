// Autosave for the grading queue. Every edit is a draft: it reaches the server a
// moment after the grader stops typing, and a copy waits in localStorage until the
// server has it, so a dropped connection, a closed tab or a crash loses nothing.
// Publishing is the same request with final: true.
//
// Requests for one submission go one at a time, in order, so a slow draft can never
// land after a newer draft or after the publish that followed it.
import { ApiError, errorMessage, type ScoreInput, type Submission } from './api';

export type SaveStatus =
  | { kind: 'saving' }
  | { kind: 'saved'; sub: Submission }
  | { kind: 'error'; message: string; retrying: boolean };

type Send = (id: string, body: ScoreInput, keepalive: boolean) => Promise<Submission>;

const BACKUP = 'grader.draft.';
const RETRY_MS = 5000;

interface Backup {
  body: ScoreInput;
  at: number;
}

export function readBackup(id: string): ScoreInput | null {
  try {
    const raw = localStorage.getItem(BACKUP + id);
    return raw ? (JSON.parse(raw) as Backup).body : null;
  } catch {
    return null;
  }
}

function writeBackup(id: string, body: ScoreInput) {
  try {
    localStorage.setItem(BACKUP + id, JSON.stringify({ body, at: Date.now() } satisfies Backup));
  } catch {
    // storage full or blocked: the server copy is all there is
  }
}

function dropBackup(id: string) {
  try {
    localStorage.removeItem(BACKUP + id);
  } catch {
    // ignore
  }
}

export class DraftSaver {
  /** The newest body not yet sent, per submission. */
  private unsent = new Map<string, ScoreInput>();
  private timers = new Map<string, ReturnType<typeof setTimeout>>();
  /** The tail of each submission's request chain. */
  private chains = new Map<string, Promise<void>>();
  private failed = new Set<string>();

  constructor(
    private send: Send,
    private onStatus: (id: string, status: SaveStatus) => void,
    private delayMs = 600,
  ) {}

  /** The grader changed something: save it as a draft shortly. */
  edit(id: string, body: ScoreInput) {
    const draft = { ...body, final: false };
    this.unsent.set(id, draft);
    writeBackup(id, draft);
    this.onStatus(id, { kind: 'saving' });
    this.schedule(id, this.delayMs);
  }

  /** Send any waiting draft for `id` now (moving to another student, leaving). */
  flush(id: string, keepalive = false): Promise<void> {
    this.clearTimer(id);
    const body = this.unsent.get(id);
    if (!body) return this.chains.get(id) ?? Promise.resolve();
    this.unsent.delete(id);
    return this.enqueue(id, body, keepalive);
  }

  flushAll(keepalive = false) {
    for (const id of [...this.unsent.keys()]) void this.flush(id, keepalive);
  }

  /** Publish: supersedes any waiting draft, and goes after anything in flight. */
  publish(id: string, body: ScoreInput): Promise<Submission> {
    this.clearTimer(id);
    this.unsent.delete(id);
    writeBackup(id, { ...body, final: false });
    let result: Submission | undefined;
    let error: unknown;
    const run = this.enqueue(id, { ...body, final: true }, false, (s) => (result = s), (e) => (error = e));
    return run.then(() => {
      if (error !== undefined) throw error;
      return result!;
    });
  }

  /** Send everything waiting and resolve once it has all been answered. */
  async settle(): Promise<void> {
    for (const id of [...this.unsent.keys()]) void this.flush(id);
    await Promise.all([...this.chains.values()]);
  }

  /** Anything that has not reached the server yet. */
  hasUnsaved(): boolean {
    return this.unsent.size > 0 || this.failed.size > 0 || this.timers.size > 0;
  }

  dispose() {
    for (const t of this.timers.values()) clearTimeout(t);
    this.timers.clear();
  }

  private schedule(id: string, ms: number) {
    this.clearTimer(id);
    this.timers.set(
      id,
      setTimeout(() => {
        this.timers.delete(id);
        void this.flush(id);
      }, ms),
    );
  }

  private clearTimer(id: string) {
    const t = this.timers.get(id);
    if (t !== undefined) clearTimeout(t);
    this.timers.delete(id);
  }

  private enqueue(
    id: string,
    body: ScoreInput,
    keepalive: boolean,
    onOk?: (s: Submission) => void,
    onErr?: (e: unknown) => void,
  ): Promise<void> {
    const prev = this.chains.get(id) ?? Promise.resolve();
    const next = prev.then(async () => {
      this.onStatus(id, { kind: 'saving' });
      try {
        const sub = await this.send(id, body, keepalive);
        this.failed.delete(id);
        // Newer edits may be waiting; their backup must stay until they are sent.
        if (!this.unsent.has(id)) dropBackup(id);
        onOk?.(sub);
        this.onStatus(id, this.unsent.has(id) ? { kind: 'saving' } : { kind: 'saved', sub });
      } catch (e) {
        this.failed.add(id);
        onErr?.(e);
        // A draft lost to the network or the server is retried, unless a newer one
        // has replaced it. A refusal (a score out of range, a signed-out session)
        // would only be refused again: it waits for the grader's next edit. A failed
        // publish is never retried behind the grader's back.
        const transient = !(e instanceof ApiError) || e.status >= 500 || e.status === 0;
        const retrying = !body.final && transient && !this.unsent.has(id);
        if (retrying) {
          this.unsent.set(id, body);
          this.schedule(id, RETRY_MS);
        }
        this.onStatus(id, { kind: 'error', message: errorMessage(e), retrying });
      }
    });
    this.chains.set(id, next);
    return next;
  }
}
