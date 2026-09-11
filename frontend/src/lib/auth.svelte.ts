// Session store. The credential is an HttpOnly cookie the browser sends on its
// own; the only thing held in JavaScript is the /auth/me profile.

import { api, ApiError, errorMessage, resetCsrf, type Enrollment, type Me, type Role } from './api';

export type AuthStatus = 'loading' | 'signed_in' | 'anonymous' | 'error';

let me = $state<Me | null>(null);
let status = $state<AuthStatus>('loading');
let error = $state<string | null>(null);

function currentLocation(): string {
  return window.location.pathname + window.location.search;
}

export const auth = {
  get me(): Me | null {
    return me;
  },
  get status(): AuthStatus {
    return status;
  },
  get error(): string | null {
    return error;
  },
  get loading(): boolean {
    return status === 'loading';
  },
  get signedIn(): boolean {
    return status === 'signed_in' && me !== null;
  },
  get isAdmin(): boolean {
    return me?.platform_admin === true;
  },

  async load(): Promise<void> {
    status = 'loading';
    error = null;
    try {
      me = await api.auth.me();
      status = 'signed_in';
    } catch (err) {
      me = null;
      if (err instanceof ApiError && err.status === 401) {
        status = 'anonymous';
      } else {
        status = 'error';
        error = errorMessage(err);
      }
    }
  },

  /** Hand the browser to the SAML flow; the server sends it back to `next`. */
  signIn(next: string = currentLocation()): void {
    window.location.assign(api.auth.loginUrl(next));
  },

  async signOut(): Promise<void> {
    try {
      await api.auth.logout();
    } finally {
      me = null;
      status = 'anonymous';
      resetCsrf();
      // In production the server 302s to the campus logout page, which a fetch
      // cannot follow; a plain reload of `/` drops all client state either way.
      window.location.assign('/');
    }
  },

  enrollment(offeringId: string): Enrollment | null {
    return me?.enrollments.find((e) => e.offering_id === offeringId) ?? null;
  },

  roleFor(offeringId: string): Role | null {
    return this.enrollment(offeringId)?.role ?? null;
  },

  isStaff(offeringId: string): boolean {
    const r = this.roleFor(offeringId);
    return r === 'ta' || r === 'instructor' || this.isAdmin;
  },

  isInstructor(offeringId: string): boolean {
    return this.roleFor(offeringId) === 'instructor' || this.isAdmin;
  },
};
