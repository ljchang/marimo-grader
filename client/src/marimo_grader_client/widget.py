"""The single anywidget behind sign-in, submit and feedback buttons.

All HTTP traffic happens in the browser (the ``_esm`` below); the kernel only
supplies the payload and receives the results through synced traits.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anywidget
import traitlets

MODES = ("signin", "submit", "feedback")
STATUSES = ("idle", "pending", "approved", "submitting", "done", "error")

_ESM = r"""
// marimo-grader-client widget. No dependencies. Every network call is made from the
// student's browser with fetch(); the kernel never sees the token.

const SUBMISSION_POLL_MS = 3000;
const SUBMISSION_POLL_LIMIT_MS = 120000;
const PAYLOAD_REFRESH_TIMEOUT_MS = 3000;

// ---- small DOM helpers -----------------------------------------------------

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  node.append(...children);
  return node;
}

function clear(node) {
  node.replaceChildren();
}

function note(kind, text) {
  return h("div", { class: `grader-note grader-${kind}` }, text);
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function fmtTime(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString();
}

function fmtPoints(x) {
  if (x === null || x === undefined) return "-";
  const n = Number(x);
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

// ---- model helpers ---------------------------------------------------------

function setModel(model, values) {
  for (const [k, v] of Object.entries(values)) model.set(k, v);
  model.save_changes();
}

function setStatus(model, status, message = "") {
  setModel(model, { status, message });
}

function serverOf(model) {
  return String(model.get("server") || "").replace(/\/+$/, "");
}

function clientName(model) {
  const c = (model.get("payload") || {}).client || {};
  return `${c.package || "marimo-grader-client"}/${c.version || "0"}`;
}

// ---- token storage ---------------------------------------------------------

function storageKey(server) {
  return `grader:${server}:token`;
}

function loadToken(server) {
  try {
    const raw = localStorage.getItem(storageKey(server));
    if (!raw) return null;
    const t = JSON.parse(raw);
    if (!t || !t.token) return null;
    if (t.expires_at && Date.parse(t.expires_at) < Date.now()) return null;
    return t;
  } catch {
    return null;
  }
}

function saveToken(server, t) {
  try {
    localStorage.setItem(storageKey(server), JSON.stringify(t));
  } catch {
    // storage may be unavailable (private mode, sandboxed iframe); ignore
  }
}

function clearToken(server) {
  try {
    localStorage.removeItem(storageKey(server));
  } catch {
    // ignore
  }
}

function currentToken(state) {
  const token = state.model.get("token");
  if (token) return { token, netid: state.model.get("netid") || "" };
  return loadToken(state.server);
}

function forgetToken(state) {
  clearToken(state.server);
  setModel(state.model, { token: "", netid: "" });
}

// ---- API -------------------------------------------------------------------

class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function api(server, path, { method = "GET", body, token } = {}) {
  if (!server) throw new ApiError(0, "no_server", "No grader server configured.");
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  let res;
  try {
    res = await fetch(`${server}/api/v1${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiError(0, "network", `Could not reach ${server} (${e.message}).`);
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = (data && data.error) || {};
    throw new ApiError(res.status, err.code || `http_${res.status}`, err.message || res.statusText);
  }
  return data;
}

// ---- server status ----------------------------------------------------------

const DISABLED_MSG =
  "Sign-in for this grader is not available yet (Dartmouth SSO is still being set up). " +
  "Check runs locally; submitting opens once sign-in is enabled.";

async function submissionsEnabled(server) {
  // Best effort: an unreachable /api/health should not block the button.
  try {
    const res = await fetch(`${server}/api/health`, { headers: { Accept: "application/json" } });
    const data = await res.json();
    return data.submissions_enabled !== false;
  } catch {
    return true;
  }
}

function newClientSubmissionId() {
  if (globalThis.crypto && crypto.randomUUID) return crypto.randomUUID();
  return `c-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// ---- sign-in (device handshake) -------------------------------------------

async function signIn(state, container, onSignedIn) {
  if (!(await submissionsEnabled(state.server))) {
    clear(container);
    container.append(note("muted", DISABLED_MSG));
    setStatus(state.model, "idle", "sign-in disabled");
    return;
  }
  const { model, server } = state;
  // Open the tab synchronously inside the click handler so popup blockers
  // allow it; we navigate it once the server hands us a verification URL.
  let tab = null;
  try {
    tab = window.open("", "_blank");
  } catch {
    tab = null;
  }
  clear(container);
  container.append(note("muted", "Contacting the grader..."));
  setStatus(model, "pending", "waiting for sign-in");

  let start;
  try {
    start = await api(server, "/auth/device", {
      method: "POST",
      body: { client: clientName(model) },
    });
  } catch (e) {
    if (tab) tab.close();
    clear(container);
    container.append(note("err", `Sign-in failed: ${e.message}`));
    setStatus(model, "error", e.message);
    return;
  }
  if (tab) {
    try {
      tab.location.href = start.verification_url;
    } catch {
      // cross-origin restrictions; the manual link below still works
    }
  }

  clear(container);
  container.append(
    h("div", { class: "grader-card" },
      h("div", { class: "grader-label" }, "Your code"),
      h("div", { class: "grader-code" }, start.user_code),
      h("div", { class: "grader-note grader-muted" },
        "A Dartmouth sign-in tab should have opened. If not, open ",
        h("a", { href: start.verification_url, target: "_blank", rel: "noopener" }, start.verification_url),
        " and enter the code above."),
      note("muted", "Waiting for approval...")));

  const deadline = Date.now() + (Number(start.expires_in) || 600) * 1000;
  const interval = Math.max(1, Number(start.interval) || 3) * 1000;
  while (state.alive && Date.now() < deadline) {
    await sleep(interval);
    let poll;
    try {
      poll = await api(server, "/auth/device/token", {
        method: "POST",
        body: { device_code: start.device_code },
      });
    } catch (e) {
      if (e.status === 0) continue; // transient network trouble; keep polling
      clear(container);
      container.append(note("err", `Sign-in failed: ${e.message}`));
      setStatus(model, "error", e.message);
      return;
    }
    if (poll.status === "approved") {
      const expiresAt = new Date(Date.now() + (Number(poll.expires_in) || 28800) * 1000).toISOString();
      saveToken(server, { token: poll.access_token, netid: poll.netid, expires_at: expiresAt });
      setModel(model, { token: poll.access_token, netid: poll.netid, status: "approved", message: "" });
      clear(container);
      container.append(signedInLine(state, container, onSignedIn, poll.netid));
      if (onSignedIn) onSignedIn({ token: poll.access_token, netid: poll.netid });
      return;
    }
    if (poll.status === "expired") {
      clear(container);
      container.append(note("err", "The sign-in code expired. Click Sign in to try again."));
      container.append(signInButton(state, container, onSignedIn));
      setStatus(model, "error", "device code expired");
      return;
    }
  }
  if (state.alive) {
    clear(container);
    container.append(note("err", "Sign-in timed out."));
    container.append(signInButton(state, container, onSignedIn));
    setStatus(model, "error", "sign-in timed out");
  }
}

function signInButton(state, container, onSignedIn, label = "Sign in with Dartmouth") {
  return h("button", {
    class: "grader-button",
    onclick: () => signIn(state, container, onSignedIn),
  }, label);
}

function signedInLine(state, container, onSignedIn, netid) {
  return h("div", { class: "grader-row" },
    h("span", { class: "grader-ok" }, `Signed in as ${netid || "(unknown)"}`),
    h("button", {
      class: "grader-button grader-secondary grader-small",
      onclick: () => {
        forgetToken(state);
        signIn(state, container, onSignedIn);
      },
    }, "Sign in again"));
}

// ---- payload refresh (asks the kernel to re-read the notebook) ------------

function refreshPayload(state) {
  const { model } = state;
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      try { model.off("msg:custom", handler); } catch { /* ignore */ }
      resolve();
    };
    const handler = (msg) => {
      if (msg && msg.type === "payload") finish();
    };
    try {
      model.on("msg:custom", handler);
      model.send({ type: "refresh" });
    } catch {
      finish();
      return;
    }
    setTimeout(finish, PAYLOAD_REFRESH_TIMEOUT_MS);
  });
}

// ---- rendering a submission ----------------------------------------------

function scoreBlock(sub) {
  const wrap = h("div", { class: "grader-card" });
  const head = `Attempt ${sub.attempt_no} submitted ${fmtTime(sub.submitted_at)}`;
  wrap.append(h("div", { class: "grader-label" }, head));
  const status = String(sub.status || "");
  if (sub.score && status === "graded") {
    const s = sub.score;
    wrap.append(h("div", { class: "grader-score" },
      `${fmtPoints(s.total)} / ${fmtPoints(s.max_points)} points`));
    if (s.feedback) wrap.append(h("div", { class: "grader-feedback" }, String(s.feedback)));
    if (s.is_final === false) wrap.append(note("muted", "Provisional score; a final grade may follow."));
  } else if (status === "failed") {
    wrap.append(note("err", "Grading failed. Your submission was recorded; please tell your instructor."));
  } else if (status === "graded") {
    wrap.append(note("muted", "Graded; score not released yet."));
  } else {
    wrap.append(note("muted", `Status: ${status || "received"}`));
  }
  return wrap;
}

// ---- modes ------------------------------------------------------------------

function renderSignin(state) {
  const { el } = state;
  const box = h("div", { class: "grader-panel" });
  el.append(box);
  const cred = currentToken(state);
  if (cred) {
    box.append(signedInLine(state, box, null, cred.netid));
    setStatus(state.model, "approved", "");
  } else {
    box.append(signInButton(state, box, null));
  }
}

function renderSubmit(state) {
  const { el, model } = state;
  const qid = model.get("question_id");
  const btn = h("button", { class: "grader-button" }, `Submit ${qid}`);
  const out = h("div", { class: "grader-panel" });
  el.append(h("div", { class: "grader-row" }, btn), out);
  btn.addEventListener("click", () => submit(state, btn, out));
}

async function submit(state, btn, out) {
  const { model, server } = state;
  const cred = currentToken(state);
  if (!cred) {
    clear(out);
    out.append(note("muted", "Sign in first, then submit."));
    out.append(signInButton(state, out, () => submit(state, btn, out)));
    return;
  }
  btn.disabled = true;
  clear(out);
  if (!(await submissionsEnabled(server))) {
    btn.disabled = false;
    out.append(note("muted", DISABLED_MSG));
    setStatus(model, "idle", "submissions disabled");
    return;
  }
  out.append(note("muted", "Collecting your notebook..."));
  setStatus(model, "submitting", "");
  await refreshPayload(state);
  const payload = model.get("payload") || {};
  if (!payload.notebook) {
    btn.disabled = false;
    clear(out);
    out.append(note("err", "The notebook source is not readable in this environment, so it cannot be submitted."));
    setStatus(model, "error", "notebook source unavailable");
    return;
  }

  let created;
  try {
    created = await api(server, "/submissions", {
      method: "POST",
      token: cred.token,
      body: {
        assignment_version_id: model.get("assignment_version_id"),
        question_id: model.get("question_id"),
        // One id per click: a retry or double-click returns the same attempt.
        client_submission_id: newClientSubmissionId(),
        ...payload,
      },
    });
  } catch (e) {
    btn.disabled = false;
    clear(out);
    if (e.status === 401) {
      forgetToken(state);
      out.append(note("muted", "Your sign-in has expired. Sign in again to submit."));
      out.append(signInButton(state, out, () => submit(state, btn, out)));
      setStatus(model, "idle", "sign-in required");
      return;
    }
    out.append(note("err", `Submission failed: ${e.message}`));
    setStatus(model, "error", `${e.code}: ${e.message}`);
    return;
  }

  setModel(model, { result: created, status: "done", message: `attempt ${created.attempt_no} received` });
  clear(out);
  const card = scoreBlock(created);
  out.append(card);
  if (created.stale) {
    out.append(
      note(
        "muted",
        `You are working on version ${created.version} of this assignment; version ` +
          `${created.latest_version} has been published. Your submission was accepted and will be ` +
          `graded against version ${created.version}. Open the assignment page to get the latest copy.`,
      ),
    );
  }
  const spinner = note("muted", "Waiting for the grader...");
  out.append(spinner);

  const deadline = Date.now() + SUBMISSION_POLL_LIMIT_MS;
  let last = created;
  while (state.alive && Date.now() < deadline) {
    await sleep(SUBMISSION_POLL_MS);
    try {
      last = await api(server, `/submissions/${created.id}`, { token: cred.token });
    } catch (e) {
      if (e.status === 0) continue;
      spinner.replaceWith(note("err", `Could not check grading status: ${e.message}`));
      btn.disabled = false;
      return;
    }
    if (last.status === "graded" || last.status === "failed") break;
  }
  setModel(model, { result: last });
  card.replaceWith(scoreBlock(last));
  if (last.status === "graded" || last.status === "failed") {
    spinner.remove();
  } else {
    spinner.replaceWith(note("muted", "Still grading. Check back later with the feedback cell."));
  }
  btn.disabled = false;
}

function renderFeedback(state) {
  const { el, model } = state;
  const out = h("div", { class: "grader-panel" });
  const btn = h("button", { class: "grader-button grader-secondary grader-small" }, "Refresh");
  el.append(h("div", { class: "grader-row" },
    h("span", { class: "grader-label" }, `Feedback for ${model.get("question_id")}`), btn), out);

  const load = async () => {
    const cred = currentToken(state);
    if (!cred) {
      clear(out);
      out.append(note("muted", "Sign in to see your feedback."));
      out.append(signInButton(state, out, load));
      return;
    }
    btn.disabled = true;
    clear(out);
    out.append(note("muted", "Loading..."));
    setStatus(model, "pending", "");
    const offering = model.get("offering_id");
    const assignment = model.get("assignment_id");
    const qid = model.get("question_id");
    let subs;
    try {
      const q = assignment ? `?assignment_id=${encodeURIComponent(assignment)}` : "";
      subs = await api(state.server, `/offerings/${encodeURIComponent(offering)}/me/submissions${q}`, {
        token: cred.token,
      });
    } catch (e) {
      btn.disabled = false;
      clear(out);
      if (e.status === 401) {
        forgetToken(state);
        out.append(note("muted", "Your sign-in has expired."));
        out.append(signInButton(state, out, load));
        setStatus(model, "idle", "sign-in required");
        return;
      }
      out.append(note("err", `Could not load feedback: ${e.message}`));
      setStatus(model, "error", `${e.code}: ${e.message}`);
      return;
    }
    btn.disabled = false;
    const mine = (Array.isArray(subs) ? subs : []).filter(
      (s) => s.qid === qid || s.question_id === qid);
    mine.sort((a, b) => (a.attempt_no || 0) - (b.attempt_no || 0));
    const latest = mine[mine.length - 1];
    clear(out);
    if (!latest) {
      out.append(note("muted", "No submissions yet for this question."));
      setModel(model, { result: {}, status: "done", message: "no submissions" });
      return;
    }
    out.append(scoreBlock(latest));
    if (mine.length > 1) out.append(note("muted", `${mine.length} attempts so far.`));
    setModel(model, { result: latest, status: "done", message: "" });
  };
  btn.addEventListener("click", load);
  load();
}

// ---- entry point -----------------------------------------------------------

function render({ model, el }) {
  el.classList.add("grader");
  const state = { model, el, server: serverOf(model), alive: true };
  const mode = model.get("mode");
  if (!state.server) {
    el.append(note("err", "No grader server configured (set grader-server in the notebook metadata or GRADER_SERVER)."));
  } else if (mode === "signin") {
    renderSignin(state);
  } else if (mode === "submit") {
    renderSubmit(state);
  } else if (mode === "feedback") {
    renderFeedback(state);
  } else {
    el.append(note("err", `Unknown widget mode: ${mode}`));
  }
  return () => {
    state.alive = false;
  };
}

export default { render };
"""

_CSS = r"""
.grader {
  --gc-accent: #00693e;
  --gc-accent-fg: #ffffff;
  --gc-ok: #1a7f4b;
  --gc-err: #b3261e;
  --gc-border: color-mix(in srgb, currentColor 22%, transparent);
  --gc-muted: color-mix(in srgb, currentColor 62%, transparent);
  --gc-surface: color-mix(in srgb, currentColor 5%, transparent);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  color: inherit;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-width: 40rem;
}
@media (prefers-color-scheme: dark) {
  .grader { --gc-accent: #2fa572; --gc-ok: #4ade80; --gc-err: #f87171; }
}
:is(.dark, [data-theme="dark"]) .grader {
  --gc-accent: #2fa572; --gc-ok: #4ade80; --gc-err: #f87171;
}
.grader-panel { display: flex; flex-direction: column; gap: 0.5rem; }
.grader-panel:empty { display: none; }
.grader-row { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
.grader-button {
  font: inherit;
  padding: 0.4rem 0.9rem;
  border-radius: 6px;
  border: 1px solid var(--gc-accent);
  background: var(--gc-accent);
  color: var(--gc-accent-fg);
  cursor: pointer;
}
.grader-button:hover:not(:disabled) { filter: brightness(1.08); }
.grader-button:disabled { opacity: 0.6; cursor: default; }
.grader-secondary { background: transparent; color: inherit; border-color: var(--gc-border); }
.grader-small { padding: 0.2rem 0.6rem; font-size: 0.9em; }
.grader-card {
  border: 1px solid var(--gc-border);
  background: var(--gc-surface);
  border-radius: 6px;
  padding: 0.6rem 0.8rem;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.grader-label { font-weight: 600; }
.grader-code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 1.5rem; letter-spacing: 0.12em; }
.grader-score { font-size: 1.15rem; font-weight: 600; }
.grader-feedback { white-space: pre-wrap; }
.grader-note { margin: 0; }
.grader-muted { color: var(--gc-muted); }
.grader-ok { color: var(--gc-ok); }
.grader-err { color: var(--gc-err); }
.grader a { color: var(--gc-accent); word-break: break-all; }
"""


class GraderWidget(anywidget.AnyWidget):
    """One widget, three modes: ``signin``, ``submit`` and ``feedback``.

    Traits synced to the browser are plain JSON. ``payload`` flows
    Python -> JS (what to submit); ``token``/``netid``/``result``/``status``/
    ``message`` flow JS -> Python so a notebook can react to them.
    """

    _esm = _ESM
    _css = _CSS

    server = traitlets.Unicode("").tag(sync=True)
    mode = traitlets.Enum(MODES, default_value="signin").tag(sync=True)
    assignment_version_id = traitlets.Unicode("").tag(sync=True)
    question_id = traitlets.Unicode("").tag(sync=True)
    offering_id = traitlets.Unicode("").tag(sync=True)
    assignment_id = traitlets.Unicode("").tag(sync=True)
    token = traitlets.Unicode("").tag(sync=True)
    netid = traitlets.Unicode("").tag(sync=True)
    payload = traitlets.Dict().tag(sync=True)
    result = traitlets.Dict().tag(sync=True)
    status = traitlets.Enum(STATUSES, default_value="idle").tag(sync=True)
    message = traitlets.Unicode("").tag(sync=True)

    def __init__(
        self, *, payload_factory: Callable[[], dict[str, Any]] | None = None, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._payload_factory = payload_factory
        self.on_msg(self._on_custom_msg)

    def _on_custom_msg(self, _widget: Any, content: Any, _buffers: Any) -> None:
        """JS asks for a fresh payload right before submitting."""
        if not isinstance(content, dict) or content.get("type") != "refresh":
            return
        if self._payload_factory is not None:
            try:
                self.payload = self._payload_factory()
            except Exception as e:  # noqa: BLE001 - surface, never crash the kernel
                self.message = f"payload refresh failed: {e}"
        self.send({"type": "payload"})

    def refresh_payload(self) -> dict[str, Any]:
        """Rebuild ``payload`` from the factory (also used by the JS refresh)."""
        if self._payload_factory is not None:
            self.payload = self._payload_factory()
        return self.payload
