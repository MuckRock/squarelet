<script lang="ts">
  import type { Organization } from "@/types";

  import "@/css/team_list_item.css";
  import people from "@/icons/people.svg";
  import UnverifiedIcon from "@/icons/unverified.svelte";
  import VerifiedIcon from "@/icons/verified.svelte";
  import LockIcon from "@/icons/lock.svelte";


  let { organization }: { organization: Organization } = $props();

  let count = $derived(organization.member_count);
  // Use avatar_medium for better performance (150x150 instead of full size)
  let avatar = $derived(organization.avatar_medium || organization.avatar_url);

  // Helper function for pluralization
  function pluralize(
    count: number,
    singular: string = "",
    plural: string = "s",
  ): string {
    return count === 1 ? singular : plural;
  }
</script>

<div class="team">
  {#if avatar}
    <div class="org-avatar">
      <img src={avatar} alt="{organization.name} avatar" />
    </div>
  {:else}
    <div class="org-avatar">
      <img src={people} alt="Organization avatar placeholder" />
    </div>
  {/if}

  <div class="info">
    <h4>{organization.name}</h4>
    <div class="status">
      {#if organization.private}
        <div class="badge">
          <span class="icon"><LockIcon /></span>
          Private
        </div>
      {/if}
      {#if organization.verified_journalist}
        <div class="badge green">
          <span class="icon"><VerifiedIcon /></span>
          Verified
        </div>
      {:else}
        <div class="badge">
          <span class="icon"><UnverifiedIcon /></span>
          Unverified
        </div>
        <span class="membership">
          {count}
          {pluralize(count, "member", "members")}
        </span>
      {/if}
    </div>
  </div>
</div>
