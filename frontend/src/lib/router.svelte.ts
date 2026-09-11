// A small history-API router. Patterns are plain paths with `:param` segments.
// Same-origin <a> clicks are intercepted so templates can use ordinary hrefs.

let path = $state(normalize(window.location.pathname));
let search = $state(window.location.search);

function normalize(p: string): string {
  if (p.length > 1 && p.endsWith('/')) return p.slice(0, -1);
  return p || '/';
}

function sync(): void {
  path = normalize(window.location.pathname);
  search = window.location.search;
}

export interface NavigateOptions {
  replace?: boolean;
}

export const router = {
  get path(): string {
    return path;
  },
  get search(): string {
    return search;
  },
  get query(): URLSearchParams {
    return new URLSearchParams(search);
  },

  navigate(to: string, opts: NavigateOptions = {}): void {
    const target = new URL(to, window.location.origin);
    if (target.origin !== window.location.origin) {
      window.location.assign(target.href);
      return;
    }
    const href = target.pathname + target.search + target.hash;
    if (opts.replace) history.replaceState(null, '', href);
    else history.pushState(null, '', href);
    sync();
    window.scrollTo({ top: 0 });
  },

  start(): void {
    window.addEventListener('popstate', sync);
    document.addEventListener('click', onClick);
  },
};

function onClick(e: MouseEvent): void {
  if (e.defaultPrevented || e.button !== 0) return;
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const el = e.target instanceof Element ? e.target.closest('a[href]') : null;
  if (!(el instanceof HTMLAnchorElement)) return;
  if (el.target && el.target !== '_self') return;
  if (el.hasAttribute('download') || el.dataset.native !== undefined) return;
  const raw = el.getAttribute('href') ?? '';
  if (raw.startsWith('#') || raw.startsWith('mailto:')) return;
  const target = new URL(el.href, window.location.origin);
  if (target.origin !== window.location.origin) return;
  // API and auth URLs must be real navigations (downloads, SAML redirects).
  if (target.pathname.startsWith('/api/') || target.pathname.startsWith('/auth/')) return;
  e.preventDefault();
  router.navigate(target.pathname + target.search + target.hash);
}

export type Params = Record<string, string>;

interface Compiled {
  regex: RegExp;
  keys: string[];
}

const cache = new Map<string, Compiled>();

function compile(pattern: string): Compiled {
  const hit = cache.get(pattern);
  if (hit) return hit;
  const keys: string[] = [];
  const source = pattern
    .split('/')
    .map((seg) => {
      if (seg.startsWith(':')) {
        keys.push(seg.slice(1));
        return '([^/]+)';
      }
      return seg.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    })
    .join('/');
  const compiled = { regex: new RegExp(`^${source}$`), keys };
  cache.set(pattern, compiled);
  return compiled;
}

/** Match `pattern` against `p`, returning decoded params or null. */
export function match(pattern: string, p: string): Params | null {
  const { regex, keys } = compile(pattern);
  const m = regex.exec(p);
  if (!m) return null;
  const params: Params = {};
  keys.forEach((k, i) => {
    params[k] = decodeURIComponent(m[i + 1] ?? '');
  });
  return params;
}
