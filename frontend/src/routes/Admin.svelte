<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage, type Course } from '$lib/api';
  import Notice from '$lib/components/Notice.svelte';
  import Audit from './Audit.svelte';
  import Loading from '$lib/components/Loading.svelte';

  let { params: _params }: { params: Record<string, string> } = $props();

  let courses = $state<Course[] | null>(null);
  let error = $state<string | null>(null);
  let message = $state<string | null>(null);

  // Forms
  let courseSlug = $state('');
  let courseTitle = $state('');
  let offeringCourse = $state('');
  let offeringTerm = $state('');
  let offeringTitle = $state('');
  let instructorOffering = $state('');
  let instructorNetid = $state('');
  let busy = $state(false);

  const allOfferings = $derived(
    (courses ?? []).flatMap((c) => (c.offerings ?? []).map((o) => ({ ...o, course: c }))),
  );

  async function load() {
    try {
      courses = await api.admin.courses();
    } catch (err) {
      error = errorMessage(err);
      courses = [];
    }
  }
  onMount(load);

  async function run(label: string, fn: () => Promise<unknown>) {
    busy = true;
    error = null;
    message = null;
    try {
      await fn();
      message = label;
      await load();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  function createCourse(e: SubmitEvent) {
    e.preventDefault();
    const slug = courseSlug.trim();
    const title = courseTitle.trim();
    void run(`Created course ${slug}.`, async () => {
      await api.admin.createCourse({ slug, title });
      courseSlug = '';
      courseTitle = '';
    });
  }

  function createOffering(e: SubmitEvent) {
    e.preventDefault();
    const term = offeringTerm.trim();
    const title = offeringTitle.trim();
    const courseId = offeringCourse;
    void run(`Created offering ${term}.`, async () => {
      await api.admin.createOffering(courseId, { term, title });
      offeringTerm = '';
      offeringTitle = '';
    });
  }

  function addInstructor(e: SubmitEvent) {
    e.preventDefault();
    const netid = instructorNetid.trim();
    const offeringId = instructorOffering;
    void run(`Added ${netid} as instructor.`, async () => {
      await api.admin.addInstructor(offeringId, { netid });
      instructorNetid = '';
    });
  }
</script>

<div class="page-head">
  <div>
    <p class="eyebrow">Platform admin</p>
    <h1>Courses, offerings, instructors</h1>
  </div>
  <span class="muted small">No student data on this page.</span>
</div>

{#if error}<Notice kind="error" label="Error">{error}</Notice>{/if}
{#if message}<Notice label="Done">{message}</Notice>{/if}

<section class="block">
  <div class="block-head"><h2>Courses <span class="count">{courses?.length ?? 0}</span></h2></div>
  {#if courses === null}
    <Loading />
  {:else if courses.length === 0}
    <p class="empty">No courses yet.</p>
  {:else}
    <div class="tablewrap">
      <table class="data">
        <thead>
          <tr><th>Slug</th><th>Title</th><th>Offerings</th><th>Id</th></tr>
        </thead>
        <tbody>
          {#each courses as c (c.id)}
            <tr>
              <td class="mono">{c.slug}</td>
              <td class="wrap">{c.title}</td>
              <td class="wrap">
                {#if c.offerings && c.offerings.length > 0}
                  {#each c.offerings as o (o.id)}
                    <span class="chip">{o.term}</span>{' '}
                  {/each}
                {:else}
                  <span class="muted">—</span>
                {/if}
              </td>
              <td class="mono muted small">{c.id}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<div class="grid-2">
  <form class="card" onsubmit={createCourse}>
    <h3>New course</h3>
    <label class="field"><span>Slug</span><input required bind:value={courseSlug} placeholder="neuroimaging" pattern="[a-z0-9-]+" /></label>
    <label class="field"><span>Title</span><input required bind:value={courseTitle} placeholder="Introduction to Neuroimaging" /></label>
    <button class="primary" type="submit" disabled={busy}>Create course</button>
  </form>

  <form class="card" onsubmit={createOffering}>
    <h3>New offering</h3>
    <label class="field">
      <span>Course</span>
      <select required bind:value={offeringCourse}>
        <option value="" disabled>Choose a course</option>
        {#each courses ?? [] as c (c.id)}
          <option value={c.id}>{c.slug} — {c.title}</option>
        {/each}
      </select>
    </label>
    <label class="field"><span>Term</span><input required bind:value={offeringTerm} placeholder="2026-fall" /></label>
    <label class="field"><span>Title</span><input required bind:value={offeringTitle} placeholder="PSYC 60, Fall 2026" /></label>
    <button class="primary" type="submit" disabled={busy || !offeringCourse}>Create offering</button>
  </form>

  <form class="card" onsubmit={addInstructor}>
    <h3>Add instructor</h3>
    <label class="field">
      <span>Offering</span>
      {#if allOfferings.length > 0}
        <select required bind:value={instructorOffering}>
          <option value="" disabled>Choose an offering</option>
          {#each allOfferings as o (o.id)}
            <option value={o.id}>{o.course.slug} · {o.term} — {o.title}</option>
          {/each}
        </select>
      {:else}
        <input required bind:value={instructorOffering} placeholder="offering id" />
      {/if}
    </label>
    <label class="field"><span>NetID</span><input required bind:value={instructorNetid} placeholder="f00abc1" /></label>
    <button class="primary" type="submit" disabled={busy || !instructorOffering}>Add instructor</button>
  </form>
</div>
<section class="block" id="audit">
  <div class="block-head"><h2>Platform audit log</h2><span class="muted small">Courses, offerings, staff, publishes, roster imports, exports. Grade changes are only visible to each offering's instructors.</span></div>
  <Audit scope="platform" />
</section>


