<script lang="ts">
  import type { User } from "@/types";
  let { user }: { user: User } = $props();
</script>

<div class="user-list-item">
  {#if user.avatar_url}
    <img src={user.avatar_url} alt={user.name || user.username} class="avatar" />
  {/if}
  <div class="info">
    <span class="name">{user.name || user.username}</span>
    <span class="username">@{user.username}</span>
  </div>
</div>
