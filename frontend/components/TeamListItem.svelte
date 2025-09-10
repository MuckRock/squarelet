<script lang="ts">
  import type { Organization } from "@/types";

  import "@/css/team_list_item.css";
  import people from "@/icons/people.svg";
  import unverified from "@/icons/unverified.svg";
  import verified from "@/icons/verified.svg";

  let { organization }: { organization: Organization } = $props();

  let count = $derived(organization.member_count);
  let avatar = $derived(organization.avatar_url);

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
      {#if organization.verified_journalist}
        <div class="badge verified">
          <img src={verified} alt="Verified" />
          Verified
        </div>
      {:else}
        <div class="badge">
          <img src={unverified} alt="Unverified" />
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
