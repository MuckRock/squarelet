# Issue 474: Search Existing Users When Creating Org Membership Invitations

## Status — All implementation complete (2026-03-12)

All seven parts are implemented and committed. E2e tests updated (switched from
`pressSequentially` to `fill` for reliability). Backend also handles adding
users who are already members of the org (returns `already_member` status).

**Remaining:** Final review, run full test suite, open PR against master.

---

## Overview

Enable org admins to search existing users when inviting members. Requires:

1. Three-state user privacy (public / private / hidden)
2. Exposing the privacy toggle in the user profile edit form
3. A user search API endpoint
4. A `UserSelect` Svelte component (built on the `OrgSearch` pattern)
5. Wiring `UserSelect` into the existing "Invite members" form

---

## Part 1 — User Privacy States (Backend)

### 1a. Add `hidden` field to `Organization` ✅

**File:** `squarelet/organizations/models/organization.py`

Done. Added `hidden` BooleanField (default `True`) at line 204.
Schema migration: `squarelet/organizations/migrations/0059_add_hidden.py`.
Data migration: `squarelet/organizations/migrations/0060_populate_hidden.py` — sets
non-individual orgs to `hidden=False`, individual orgs to `private=False`, then
un-hides individuals with verified primary email, any charge, or membership in a
`verified_journalist` org. Fully reversible.

### 1b. Signal to un-hide users when conditions are met ✅

**File:** `squarelet/users/signals.py`

Done. Extended `email_confirmed` to set `hidden=False` on primary email confirm.
Added `charge_created` post_save handler for `Charge` model (checks
`organization.individual` before updating). Tests in
`squarelet/users/tests/test_signals.py` (4 new tests).

### 1c. Change individual org `private` default — DONE

Changed `create_individual` in `squarelet/organizations/querysets.py` from
`private=True` to `private=False`. Updated `IndividualOrganizationFactory` to
match (`private=False`, `hidden=True`). Updated existing tests in
`test_querysets.py` to reflect the new default.

---

## Part 2 — Expose Privacy Setting in User Profile Edit

### 2a. Form changes ✅

**File:** `squarelet/users/forms.py`

Done. Added non-model `BooleanField` `private` to `UserUpdateForm`, initialized
from `individual_organization.private` in `__init__`. `UserUpdateView.form_valid`
saves it onto `individual_organization`. Tests in
`squarelet/users/tests/test_views.py` (3 new tests: field present, sets true,
sets false).

### 2b. Template ✅

**File:** `squarelet/templates/users/user_form.html`

Added checkbox detection: fields with `widget.input_type == "checkbox"` render
inline (input before label) using existing `field-checkbox` / `field-label-inline`
CSS classes. Non-checkbox fields render as before.

---

## Part 3 — User Search API Endpoint

### 3a. UserManager — `get_searchable` — DONE

**File:** `squarelet/users/managers.py`

Implemented `get_searchable(user)` on `UserManager`. Tests in
`squarelet/users/tests/test_managers.py` (6 tests covering staff, hidden,
public, private/orgmate, private/stranger, and deduplication).

### 3b. Lightweight serializer ✅

**File:** `squarelet/users/fe_api/serializers.py`

Done. Added `UserSearchSerializer` with safe fields only (id, uuid, username,
name, avatar_url — no email).

### 3c. UserViewSet — add search ✅

**File:** `squarelet/users/fe_api/viewsets.py`

Done. Rewired `get_queryset` to use `get_searchable` for list action,
`get_serializer_class` returns `UserSearchSerializer` for list and
`UserSerializer` for detail. Search uses PostgreSQL full-text `SearchVector`
with prefix matching (`search_type="raw"` with `:*` suffix) to avoid
`LIKE`/`ILIKE` errors from the `case_insensitive` collation on `username`
and `name` fields.

Endpoint: `GET /fe_api/users/?search=<query>`

Tests in `squarelet/users/fe_api/test_user_viewsets.py` (3 new tests:
search by username, hidden exclusion, safe fields only).

### 3d. URL router ✅

Already registered in `config/urls.py` as `fe_api_router.register(r"users", ...)`.

---

## Part 4 — Frontend: `UserListItem` Svelte Component ✅

**File:** `frontend/components/UserListItem.svelte` (new)

Done. Displays a single user in the dropdown list. Modelled after `TeamListItem.svelte`.

```svelte
<script lang="ts">
  import type { User } from "@/types";
  let { user }: { user: User } = $props();
</script>

<div class="user-list-item">
  <img src={user.avatar_url} alt={user.name} class="avatar" />
  <div class="info">
    <span class="name">{user.name || user.username}</span>
    <span class="username">@{user.username}</span>
  </div>
</div>
```

Add `User` type to `frontend/types.d.ts` (where `Organization` is already defined):

```typescript
export interface User {
  id: number;
  uuid: string;
  username: string;
  name: string;
  avatar_url: string;
}
```

---

## Part 5 — Frontend: `UserSelect` Svelte Component ✅

**File:** `frontend/components/UserSelect.svelte` (new)

Done. A multi-select widget that:

- Fetches users via `/fe_api/users/?search=[query]`
- Supports `creatable` mode so email-like input generates a synthetic "invite by email" option
- Shows selections as chips (user chip vs email chip styled differently)
- Emits a list of `{ type: "user", id: number } | { type: "email", email: string }`

Rough structure (Svelte 5, Svelecte):

**Note:** Svelecte's `fetchCallback` receives only `(response)` — the query string
is **not** passed (see `OrgSearch.svelte` for the existing pattern). Email detection
cannot happen inside `fetchCallback`. Instead, use Svelecte's `creatable` prop to
allow free-text entry, and validate/tag email entries via `createFilter` and
`createTransform`.

```svelte
<script lang="ts">
  import type { User } from "@/types";

  import Svelecte from "svelecte";
  import UserListItem from "./UserListItem.svelte";

  type Selection =
    | { type: "user"; id: number; username: string; name: string; avatar_url: string }
    | { type: "email"; email: string; name: string; id: string };

  interface Props {
    onChange?: (selections: Selection[]) => void;
  }

  let { onChange }: Props = $props();

  let selections: Selection[] = $state([]);
  const fetchProps: RequestInit = { credentials: "include" };

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function fetchCallback(resp: { count: number; results: User[] }): User[] {
    return resp.results;
  }

  /** Only allow creating items that look like email addresses */
  function createFilter(query: string): boolean {
    return emailRegex.test(query);
  }

  /** Transform a created item (email string) into a Selection */
  function createTransform(query: string): Selection {
    return { type: "email", email: query, name: query, id: `email:${query}` };
  }

  function handleChange(next: Selection[]) {
    selections = next;
    onChange?.(next);
  }
</script>

<Svelecte
  multiple
  creatable
  name="invitees"
  placeholder="Search users or enter an email…"
  bind:value={selections}
  valueAsObject
  labelField="name"
  fetch="/fe_api/users/?search=[query]"
  {fetchCallback}
  {fetchProps}
  {createFilter}
  {createHandler}
  fetchResetOnBlur={false}
  resetOnBlur={false}
  lazyDropdown={false}
  {handleChange}
>
  {#snippet option(item: Selection)}
    {#if item.type === "email"}
      <div class="email-option">Invite <strong>{item.email}</strong> by email</div>
    {:else}
      <UserListItem user={item} />
    {/if}
  {/snippet}

  {#snippet selection(selectedOptions: Selection[], bindItem)}
    {#each selectedOptions as sel (sel.id ?? sel.email)}
      <div class="chip {sel.type}">
        {sel.type === "email" ? sel.email : (sel.name || sel.username)}
        <button data-action="deselect" use:bindItem={sel}>&times;</button>
      </div>
    {/each}
  {/snippet}
</Svelecte>
```

---

## Part 6 — Frontend: Wire Into "Invite Members" Form ✅

Progressive enhancement: the form keeps its Django `method="POST"` as a no-JS
fallback. When JS is available, submission is intercepted and each invitation is
posted individually to `POST /fe_api/invitations/` with inline feedback.

### 6a. Template ✅

**File:** `squarelet/templates/organizations/organization_managemembers.html`

Done. Replaced the existing `<input type="email" name="emails" multiple ...>` with:

- A `<div id="user-select"></div>` mount point for the `UserSelect` component
- A plain `<input type="email" name="emails">` fallback beneath it (visible only
  when JS is absent, hidden via CSS once the component mounts)

Add `data-org-id="{{ organization.pk }}"` to the form element so the TS
layer can include the org's integer pk in the REST POST body.

### 6b. TypeScript ✅

**File:** `frontend/views/organization_managemembers.svelte.ts`

Done. Mounts `UserSelect` onto `#user-select`. Intercepts the form's `submit` event
and POSTs each selection to `POST /fe_api/invitations/`, with inline feedback
without a full page reload.

```typescript
import { mount } from "svelte";
import UserSelect from "@/components/UserSelect.svelte";
import { showAlert } from "../alerts";

type Selection =
  | {
      type: "user";
      id: number;
      username: string;
      name: string;
      avatar_url: string;
    }
  | { type: "email"; email: string; name: string; id: string };

function main() {
  const el = document.getElementById("user-select");
  if (!el) return; // no-JS: form submits normally to Django view

  const form = el.closest("form") as HTMLFormElement;
  const submitBtn = form.querySelector<HTMLButtonElement>(
    '[name="action"][value="addmember"]',
  );
  const orgId = form.dataset.orgId; // set via data-org-id="{{ organization.pk }}" in template
  let selections: Selection[] = [];

  // Hide the plain email fallback input, show the Svelte widget
  form.querySelector(".email-fallback")?.setAttribute("hidden", "");

  mount(UserSelect, {
    target: el,
    props: {
      onChange(next: Selection[]) {
        selections = next;
        if (submitBtn) submitBtn.disabled = next.length === 0;
      },
    },
  });

  if (submitBtn) submitBtn.disabled = true;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const role =
      form.querySelector<HTMLSelectElement>('[name="role"]')?.value ?? "0";
    const csrf =
      form.querySelector<HTMLInputElement>('[name="csrfmiddlewaretoken"]')
        ?.value ?? "";

    const results = await Promise.allSettled(
      selections.map((sel) => {
        // For user selections, POST the user ID (no email available from search).
        // For email selections, POST the email string.
        const body: Record<string, unknown> = {
          organization: orgId,
          role: parseInt(role),
          request: false,
        };
        if (sel.type === "user") {
          body.user = sel.id;
        } else {
          body.email = sel.email;
        }
        return fetch("/fe_api/invitations/", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify(body),
        }).then((r) => {
          if (!r.ok) throw r;
          return r;
        });
      }),
    );

    const sent = results.filter((r) => r.status === "fulfilled").length;
    const failed = results.length - sent;
    if (sent > 0)
      showAlert(`${sent} invitation${sent !== 1 ? "s" : ""} sent.`, "success", {
        autoDismiss: true,
      });
    if (failed > 0)
      showAlert(
        `${failed} invitation${failed !== 1 ? "s" : ""} failed to send.`,
        "error",
      );
    selections = [];
  });

  // existing clipboard logic...
}
```

### 6c. Backend: `InvitationViewSet.perform_create` ✅

**File:** `squarelet/organizations/fe_api/viewsets.py`

Done. Moved misplaced `perform_create` from `InvitationSerializer` (where it was
a no-op) to `InvitationViewSet`. Calls `invitation.send()` after save. Test in
`squarelet/organizations/fe_api/test_viewsets.py` (`test_create_invitation_sends_email`).

Note: `user` is read-only on `InvitationSerializer`, so the frontend must send
`email` for both user-type and email-type selections. The `Invitation` model's
`email` field is required for sending.

### 6d. Django POST fallback ✅

**File:** `squarelet/organizations/views/members.py`

No changes needed. The existing `_handle_add_member` / `AddMemberForm` path
handles the no-JS fallback: a plain email address typed into the fallback input
submits as `name="emails"` to the Django view exactly as before.

---

## Part 7 — Tests

### Backend tests

**Done:**

- `squarelet/users/tests/test_managers.py` — 6 tests for `get_searchable` visibility
  (staff sees all, hidden excluded, public visible, private visible to orgmates,
  private hidden from strangers, no duplicates)
- `squarelet/users/tests/test_signals.py` — 4 new tests for un-hide signals
  (email confirm unhides, non-primary doesn't unhide, charge unhides individual,
  charge doesn't unhide group)
- `squarelet/users/fe_api/test_user_viewsets.py` — 3 new tests for search API
  (search by username, hidden exclusion, safe fields only). Updated 1 existing test
  for hidden-by-default.
- `squarelet/organizations/tests/test_querysets.py` — updated `test_create_individual_basic`
  and `test_get_viewable` to reflect new `private=False` default

- `squarelet/organizations/fe_api/test_viewsets.py` —
  `test_create_invitation_sends_email` verifies `send()` is called on POST
- `squarelet/users/tests/test_views.py` — 3 new tests for privacy toggle
  (field present, sets true, sets false)

### Frontend tests

Not in scope for this plan (no existing frontend tests in the codebase).

---

## File Change Summary

| File                                                                | Change                                                         |
| ------------------------------------------------------------------- | -------------------------------------------------------------- |
| `squarelet/organizations/models/organization.py`                    | Add `hidden` BooleanField ✅                                   |
| `squarelet/organizations/migrations/0059_add_hidden.py`             | New migration ✅                                               |
| `squarelet/organizations/querysets.py`                              | Change `create_individual` default `private=True` → `False` ✅ |
| `squarelet/users/signals.py`                                        | Add signals to set `hidden=False` on email verify / payment ✅ |
| `squarelet/users/forms.py`                                          | Add `private` field to `UserUpdateForm` ✅                     |
| `squarelet/users/views.py`                                          | Save `private` to `individual_organization` in update view ✅  |
| `squarelet/users/managers.py`                                       | Add `get_searchable(user)` manager method ✅                   |
| `squarelet/users/fe_api/serializers.py`                             | Add `UserSearchSerializer` ✅                                  |
| `squarelet/users/fe_api/viewsets.py`                                | Add search, filter, `get_searchable` to `UserViewSet` ✅       |
| `squarelet/organizations/fe_api/viewsets.py`                        | Call `invitation.send()` in `perform_create` ✅                |
| `squarelet/templates/users/user_form.html`                          | Checkbox inline rendering ✅                                   |
| `squarelet/templates/organizations/organization_managemembers.html` | Replace email input with `#user-select` mount point ✅         |
| `frontend/components/UserListItem.svelte`                           | New component ✅                                               |
| `frontend/components/UserSelect.svelte`                             | New component ✅                                               |
| `frontend/views/organization_managemembers.svelte.ts`               | Mount `UserSelect`, intercept submit, POST to REST API ✅      |
| `frontend/types.d.ts`                                               | Add `User` interface ✅                                        |

---

## Open Questions / Decisions — All Resolved

1. **User search access** — resolved. The manage-members page is gated by
   `organizations.can_manage_members` (granted to org admins and staff with an
   explicit DB-assigned permission; staff status alone is not enough). The search
   API endpoint uses `IsAuthenticated`, which is sufficient since `UserSelect`
   only appears on the already-gated page and results only expose safe public
   fields (username, name, avatar — no email).

2. **Invitation submission** — resolved. Use client-side `POST /fe_api/invitations/`
   with progressive enhancement: the form keeps its standard `method="POST"` action
   pointing at the Django view as a no-JS fallback. When JS is available, the
   `UserSelect` component intercepts submission, posts each invitation to the REST
   API, and shows inline feedback without a full page reload.
