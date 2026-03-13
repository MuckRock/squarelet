<script lang="ts">
  import type { Organization } from "@/types";

  import TeamListItem from "./TeamListItem.svelte";

  let results: Organization[] = $state([]);
  let searched = $state(false);
  let timeout: ReturnType<typeof setTimeout> | undefined;

  function onInput(event: Event) {
    const query = (event.target as HTMLInputElement).value.trim();
    clearTimeout(timeout);

    if (query.length < 2) {
      results = [];
      searched = false;
      return;
    }

    timeout = setTimeout(async () => {
      const url = `/fe_api/organizations/?individual=false&search=${encodeURIComponent(query)}&fuzzy=true`;
      try {
        const resp = await fetch(url, { credentials: "include" });
        const data = await resp.json();
        results = data.results ?? [];
      } catch {
        results = [];
      }
      searched = true;
    }, 500);
  }

  // Find the name input and attach the listener
  $effect(() => {
    const input = document.querySelector<HTMLInputElement>('input[name="name"]');
    if (input) {
      input.addEventListener("input", onInput);
      return () => input.removeEventListener("input", onInput);
    }
  });
</script>

{#if results.length > 0}
  <div class="card">
    <p class="heading">It looks like {results.length > 1 ? 'organizations with similar names are' : 'an organization with a similar name is'} already up and running on MuckRock:</p>
    <ul class="results">
      {#each results as org (org.id)}
        <li>
          <a href="/organizations/{org.slug}/" target="_blank" rel="noopener">
            <TeamListItem organization={org} />
          </a>
        </li>
      {/each}
    </ul>
    <p>
      If the organization you're trying to create is already set up on MuckRock, please look for the <b>Request to Join</b> option on the organization's profile page. Please <a href="mailto:info@muckrock.com">contact support</a> if the admins listed have left the organization.
    </p>
  </div>
{:else if searched}
  <p class="hint">No similarly named organizations found.</p>
{:else}
  <p class="hint">To discourage duplicate organizations, any existing organizations with similar names will appear here.</p>
{/if}

<style>
  .card {
    padding: 1rem;
    color: var(--gray-5);
  }

  .hint {
    width: 100%;
    color: var(--gray-4);
    border: 1px solid var(--gray-2);
    border-radius: 8px;
    padding: 1rem;
    box-sizing: border-box;
  }

  p {
    margin: 0;
  }

  .heading {
    font-weight: 600;
  }

  .results {
    list-style: none;
    padding: 0;
    margin: 1rem 0;
  }

  .results li {
    margin-bottom: 0.5rem;
  }

  .results a {
    text-decoration: none;
    color: inherit;
    display: block;
  }

  .results a:hover {
    background: var(--color-surface-hover, #f5f5f5);
    border-radius: 4px;
  }
</style>
