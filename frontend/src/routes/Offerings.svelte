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
    <p class="eyebrow">Offerings</p>
    <h1>{auth.me?.display_name ?? auth.me?.netid}</h1>
  </div>
  {#if auth.isAdmin}
    <a class="btn" href="/admin">Platform admin</a>
  {/if}
</div>

{#if error}
  <Notice kind="error" label="Could not load offerings">{error}</Notice>
{/if}

{#if offerings === null}
  <Loading />
{:else if offerings.length === 0}
  <p class="empty">You are not enrolled in any offering. Instructors can add you from the roster page.</p>
{:else}
  <div class="tablewrap">
    <table class="data">
      <thead>
        <tr>
          <th>Course</th>
          <th>Term</th>
          <th>Title</th>
          <th>Role</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {#each offerings as o (o.offering_id)}
          <tr>
            <td class="mono">{o.course_slug}</td>
            <td>{o.term}</td>
            <td class="wrap"><a href={homeFor(o)}>{o.title}</a></td>
            <td><span class="chip role">{o.role}</span></td>
            <td>
              {#if o.role !== 'student'}
                <a class="small" href="/o/{o.offering_id}">Triage</a>
                {#if o.role === 'instructor'}
                  <span class="muted"> · </span><a class="small" href="/o/{o.offering_id}/assignments">Assignments</a>
                  <span class="muted"> · </span><a class="small" href="/o/{o.offering_id}/roster">Roster</a>
                {/if}
              {:else}
                <a class="small" href="/me/{o.offering_id}">Assignments and feedback</a>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}
