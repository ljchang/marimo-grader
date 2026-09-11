<script lang="ts">
  import type { Component } from 'svelte';
  import { router, match, type Params } from '$lib/router.svelte';
  import { auth } from '$lib/auth.svelte';
  import TopBar from '$lib/components/TopBar.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import Loading from '$lib/components/Loading.svelte';

  import Offerings from './routes/Offerings.svelte';
  import Triage from './routes/Triage.svelte';
  import GradeQueue from './routes/GradeQueue.svelte';
  import StudentHistory from './routes/StudentHistory.svelte';
  import Roster from './routes/Roster.svelte';
  import Assignments from './routes/Assignments.svelte';
  import Audit from './routes/Audit.svelte';
  import StudentPortal from './routes/StudentPortal.svelte';
  import Admin from './routes/Admin.svelte';
  import SignIn from './routes/SignIn.svelte';
  import NotFound from './routes/NotFound.svelte';

  type Access = 'public' | 'signed_in' | 'enrolled' | 'staff' | 'instructor' | 'admin';

  interface RouteDef {
    pattern: string;
    component: Component<{ params: Params }>;
    access: Access;
    /** Grading queue wants the whole viewport. */
    full?: boolean;
  }

  const routes: RouteDef[] = [
    { pattern: '/', component: Offerings, access: 'signed_in' },
    { pattern: '/admin', component: Admin, access: 'admin' },
    { pattern: '/o/:offering', component: Triage, access: 'staff' },
    { pattern: '/o/:offering/grade/:questionId', component: GradeQueue, access: 'staff', full: true },
    { pattern: '/o/:offering/students/:netid', component: StudentHistory, access: 'staff' },
    { pattern: '/o/:offering/roster', component: Roster, access: 'instructor' },
    { pattern: '/o/:offering/assignments', component: Assignments, access: 'instructor' },
    { pattern: '/o/:offering/audit', component: Audit, access: 'instructor' },
    { pattern: '/me/:offering', component: StudentPortal, access: 'enrolled' },
  ];

  const matched = $derived.by(() => {
    for (const route of routes) {
      const params = match(route.pattern, router.path);
      if (params) return { route, params, key: `${route.pattern}|${JSON.stringify(params)}` };
    }
    return null;
  });

  const offering = $derived(
    matched?.params.offering ? auth.enrollment(matched.params.offering) : null,
  );

  const denial = $derived.by((): string | null => {
    if (!matched) return null;
    const { access, pattern } = matched.route;
    if (access === 'public') return null;
    if (!auth.signedIn) return 'sign_in';
    const id = matched.params.offering;
    if (access === 'admin' && !auth.isAdmin) return 'Platform administrators only.';
    if (id !== undefined && !auth.enrollment(id) && !auth.isAdmin) {
      return 'You are not enrolled in this offering.';
    }
    if (access === 'staff' && id !== undefined && !auth.isStaff(id)) {
      return 'Instructors and TAs only.';
    }
    if (access === 'instructor' && id !== undefined && !auth.isInstructor(id)) {
      return 'Instructors only.';
    }
    void pattern;
    return null;
  });

  $effect(() => {
    const parts = ['DartBrains Grader'];
    if (offering) parts.unshift(`${offering.course_slug} ${offering.term}`);
    document.title = parts.join(' · ');
  });
</script>

<TopBar {offering} />

{#if auth.loading}
  <main class="page"><Loading label="Checking session" /></main>
{:else if auth.status === 'error'}
  <main class="page narrow">
    <Notice kind="error" label="Session check failed">
      {auth.error}. <button class="quiet" onclick={() => auth.load()}>Retry</button>
    </Notice>
  </main>
{:else if !matched}
  <NotFound />
{:else if denial === 'sign_in'}
  <SignIn />
{:else if denial}
  <main class="page narrow">
    <Notice kind="warn" label="Not available">{denial} <a href="/">Back to your offerings.</a></Notice>
  </main>
{:else}
  {#key matched.key}
    {@const Page = matched.route.component}
    <main class="page" class:full={matched.route.full === true}>
      <Page params={matched.params} />
    </main>
  {/key}
{/if}
