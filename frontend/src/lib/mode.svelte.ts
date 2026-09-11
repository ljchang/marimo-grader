// UI mode for accounts that are both platform admins and teaching staff.
// "teaching" shows course navigation only; "admin" shows platform administration only.
// Purely a presentation choice: permissions are enforced by the server regardless.

export type UiMode = 'teaching' | 'admin';

const KEY = 'grader:ui-mode';

function read(): UiMode {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'admin' ? 'admin' : 'teaching';
  } catch {
    return 'teaching';
  }
}

let current = $state<UiMode>(read());

export const uiMode = {
  get value(): UiMode {
    return current;
  },
  set(mode: UiMode) {
    current = mode;
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      /* private mode or blocked storage: keep in memory only */
    }
  },
  /** Keep the mode consistent with the route family the user navigated to. */
  followPath(path: string) {
    if (path === '/admin' || path.startsWith('/admin/')) {
      if (current !== 'admin') this.set('admin');
    } else if (path.startsWith('/o/') || path.startsWith('/me/')) {
      if (current !== 'teaching') this.set('teaching');
    }
  },
};
