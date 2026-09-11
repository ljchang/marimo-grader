<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage, type Offering } from '$lib/api';
  import { auth } from '$lib/auth.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import Loading from '$lib/components/Loading.svelte';

  let { params: _params }: { params: Record<string, string> } = $props();

  let offerings = $state<Offering[] | null>(null);
  let error = $state<string | null>(null);

  onMount(async () => {
    try {
      offerings = await api.offerings.list();
    } catch (err) {
      error = errorMessage(err);
      // Fall back to what /auth/me already told us.
      offerings = auth.me?.enrollments ?? [];
    }
  });

  function homeFor(o: Offering): string {
    return o.role === 'student' ? `/me/${o.offering_id}` : `/o/${o.offering_id}`;
  }
</script>

<div class="page-head">
  <div>
    <h1>Your courses</h1>
    <p class="eyebrow">Signed in as {auth.me?.display_name ?? auth.me?.netid}</p>
  </div>
</div>

{#if error}
  <Notice kind="error" label="Could not load your courses">{error}</Notice>
{/if}

{#if offerings === null}
  <Loading />
{:else if offerings.length === 0}
  <p class="empty">You are not enrolled in any course here yet. Your instructor adds students from the Canvas roster; ask them if you expected to see one.</p>
{:else}
  <div class="tablewrap">
    <table class="data">
      <thead>
        <tr>
          <th>Course</th>
          <th>Term</th>
          <th>Your role</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {#each offerings as o (o.offering_id)}
          <tr>
            <td class="wrap"><a href={homeFor(o)}><strong>{o.title}</strong></a><span class="sub mono">{o.course_slug}</span></td>
            <td>{o.term}</td>
            <td>{o.role === 'ta' ? 'Teaching assistant' : o.role === 'instructor' ? 'Instructor' : 'Student'}</td>
            <td><a href={homeFor(o)}>{o.role === 'student' ? 'Assignments and feedback' : 'Open course'}</a></td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}
