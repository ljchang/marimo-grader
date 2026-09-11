# DartBrains Grader frontend

Svelte 5 (runes) + TypeScript + Vite. One static bundle served from the same
origin as the API. Sign-in is the SAML redirect (`/api/v1/auth/login`), the
session is an HttpOnly cookie, and every mutating request carries an
`X-CSRF-Token` header fetched from `/api/v1/auth/csrf`. Nothing is kept in
`localStorage`.

## Run in development

Requires Node 22.12+ and pnpm 11 (`corepack enable` will fetch it).

```sh
cd frontend
pnpm install
pnpm dev            # http://localhost:5173
```

The dev server proxies `/api` and `/auth` to `http://localhost:8000`, so start
the backend there first. To point at a different backend put
`GRADER_BACKEND_URL=http://host:port` in `frontend/.env.local`.

With the backend in `GRADER_AUTH_MODE=dev`, open
`http://localhost:5173/api/v1/auth/dev-login?netid=f00abc1&next=/` to get a
session for any NetID without SAML.

## Checks and build

```sh
pnpm check          # svelte-check + tsc (must be clean)
pnpm build          # writes dist/
pnpm preview        # serves dist/ locally (no API proxy)
```

## Routes

| Path | Who | View |
|---|---|---|
| `/` | everyone | Offerings you belong to, with your role |
| `/o/:offering` | instructor, TA | Triage panel, then the roster grid; live via SSE |
| `/o/:offering/grade/:questionId` | instructor, TA | Grading queue: sandboxed render, rubric, feedback, `j`/`k`, `Cmd/Ctrl+Enter` |
| `/o/:offering/students/:netid` | instructor, TA | One student's attempts across assignments |
| `/o/:offering/roster` | instructor | Canvas CSV / Banner import with preview, then apply |
| `/o/:offering/assignments` | instructor | Settings, question list, version upload, Canvas export link |
| `/me/:offering` | student | Assignments, status, grade, every attempt with feedback |
| `/admin` | platform admin | Courses, offerings, instructors |

Role checks in the router are a convenience; every view is backed by an API
call that enforces the same rule server-side.

## Layout

```
src/
  main.ts                 mounts App, starts the router, loads /auth/me
  App.svelte              route table, access guard, page shell
  app.css                 design tokens (from docs/design.html) and base styles
  lib/
    api.ts                typed client for every endpoint in docs/api.md
    auth.svelte.ts        rune store for the session (/auth/me, signIn, signOut)
    router.svelte.ts      history-API router, link interception, pattern matching
    events.ts             SSE subscription helper and debounce
    format.ts             dates, points, grade-policy helpers
    components/           TopBar, Notice, StateChip, RenderFrame, Loading
  routes/                 one component per route above
```

## Docker

```sh
docker build -t grader-frontend .
```

The final stage is `FROM scratch` containing only `/app/dist`; copy it out or
use it as a build stage for the nginx image defined under `deploy/`.
