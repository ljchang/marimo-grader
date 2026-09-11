// One SSE stream per offering. EventSource reconnects on its own; we only
// surface the connection state so pages can show a quiet "live" marker.

import { api, type GraderEvent, type GraderEventType } from './api';

export type StreamState = 'connecting' | 'open' | 'reconnecting' | 'closed';

const EVENT_TYPES: GraderEventType[] = [
  'submission.received',
  'submission.graded',
  'score.updated',
];

export function subscribeEvents(
  offeringId: string,
  onEvent: (event: GraderEvent) => void,
  onState?: (state: StreamState) => void,
): () => void {
  if (typeof EventSource === 'undefined') {
    onState?.('closed');
    return () => {};
  }
  const es = new EventSource(api.events.url(offeringId), { withCredentials: true });
  onState?.('connecting');
  es.onopen = () => onState?.('open');
  es.onerror = () => onState?.(es.readyState === EventSource.CLOSED ? 'closed' : 'reconnecting');
  for (const type of EVENT_TYPES) {
    es.addEventListener(type, (raw) => {
      const msg = raw as MessageEvent<string>;
      let payload: Partial<GraderEvent> = {};
      try {
        payload = JSON.parse(msg.data) as Partial<GraderEvent>;
      } catch {
        // malformed frame; still notify so listeners can refresh
      }
      onEvent({
        type,
        submission_id: payload.submission_id ?? '',
        question_id: payload.question_id ?? '',
        netid: payload.netid ?? '',
      });
    });
  }
  return () => {
    es.close();
    onState?.('closed');
  };
}

/** Coalesce bursts of events into one call after `wait` ms of quiet. */
export function debounce<A extends unknown[]>(fn: (...args: A) => void, wait = 400) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const wrapped = (...args: A) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, wait);
  };
  wrapped.cancel = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };
  return wrapped;
}
