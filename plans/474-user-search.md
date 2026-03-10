# Issue 474: Search Existing Users When Creating Org Membership Invitations

## Overview

Enable org admins to search existing users when inviting members. Requires:

1. Three-state user privacy (public / private / hidden)
2. Exposing the privacy toggle in the user profile edit form
3. A user search API endpoint
4. A `UserSelect` Svelte component (built on the `OrgSearch` pattern)
5. Wiring `UserSelect` into the existing "Invite members" form

---

## Part 1 — User Privacy States (Backend)

### 1a. Add `hidden` field to `Organization`

**File:** `squarelet/organizations/models/organization.py`

Add a `hidden` BooleanField to the `Organization` model. For individual orgs
this tracks whether the user is "hidden" from search (i.e., not yet verified,
no payment, no confirmed email). For non-individual orgs this field is unused
and should default to `False`.

```python
hidden = models.BooleanField(
    _("hidden"),
    default=True,
    help_text=_(
        "Individual accounts are hidden until the user has verified their email, "
        "made a payment, or been verified by association. Hidden accounts do not "
        "appear in search results."
    ),
)
```

**Migration:** Generate a new migration. New users default to `hidden=True`.
The data migration will:

- Set all non-individual orgs: `hidden=False`, `private` unchanged.
- Set individual orgs: `private=False` (making all existing users public by default).
- Then apply hidden logic: set `hidden=False` for individual orgs whose user has
  ≥1 verified email, OR has any charge, OR is a member of a `verified_journalist` org.
- Individual orgs that meet none of those conditions remain `hidden=True`.

### 1b. Signal to un-hide users when conditions are met

**File:** `squarelet/users/signals.py` (already exists — extend it)

Connect to:

- `allauth` `email_confirmed` signal → mark `user.individual_organization.hidden = False`
- `Charge` post-save signal → mark the org's owner as `hidden = False`
- Possibly `Membership` post-save on verified orgs → cascade

### 1c. Change individual org `private` default

Currently, `create_individual` (in `OrganizationQuerySet`) creates individual
orgs with `private=True`. Per the issue, a user is "public by default" (but
hidden until conditions are met). So the `private` field should default to
`False` for newly created individual orgs.

**File:** `squarelet/organizations/querysets.py`, `create_individual` method —
change `private=True` to `private=False`. Existing individual orgs are handled
by the data migration in Part 1a.

---

## Part 2 — Expose Privacy Setting in User Profile Edit

### 2a. Form changes

**File:** `squarelet/users/forms.py`

The `UserUpdateForm` currently models `User`. The `private` field lives on
`user.individual_organization` (an `Organization` instance). Two options:

Add a non-model `BooleanField` to `UserUpdateForm` and manually save it to
`user.individual_organization` in the view.

```python
private = forms.BooleanField(
    label=_("Private account"),
    required=False,
    help_text=_(
        "When enabled, your profile is only visible to MuckRock staff "
        "and members of organizations you belong to."
    ),
)

def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    if self.instance and self.instance.pk:
        self.fields["private"].initial = self.instance.individual_organization.private
```

The view (`squarelet/users/views.py`, `UserUpdateView`) saves `private` onto
`user.individual_organization` after saving the user.

### 2b. Template

**File:** `squarelet/templates/users/user_form.html`

The template already iterates `{% for field in form %}`, so the new `private`
checkbox field will render automatically. No template changes needed unless we
want special styling or positioning.

---

## Part 3 — User Search API Endpoint

### 3a. UserQuerySet — `get_searchable`

**File:** `squarelet/users/managers.py` (or a new `squarelet/users/querysets.py`)

Add a `get_searchable(requesting_user)` method to the `User` queryset:

```python
def get_searchable(self, user):
    """Return users visible in search to `user`."""
    if user.is_staff:
        return self
    # Never show hidden users
    qs = self.filter(individual_organization__hidden=False)
    # Private users are only visible to org-mates
    qs = qs.filter(
        Q(individual_organization__private=False)
        | Q(organizations__users=user)
    ).distinct()
    return qs
```

### 3b. Lightweight serializer

**File:** `squarelet/users/fe_api/serializers.py`

Add a `UserSearchSerializer` with only public-safe fields (no email):

```python
class UserSearchSerializer(serializers.ModelSerializer):
    uuid = serializers.UUIDField(read_only=True)
    avatar_url = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ("id", "uuid", "username", "name", "avatar_url")
        read_only_fields = fields
```

### 3c. UserViewSet — add search

**File:** `squarelet/users/fe_api/viewsets.py`

Extend `UserViewSet`:

```python
class UserViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (IsAuthenticated,)
    lookup_field = "id"
    filter_backends = [filters.SearchFilter]
    search_fields = ["username", "name"]

    def get_serializer_class(self):
        if self.action == "list":
            return UserSearchSerializer
        return UserSerializer  # existing detailed serializer

    def get_queryset(self):
        if self.action == "list":
            return User.objects.get_searchable(self.request.user)
        return User.objects.prefetch_related("organizations")
```

Endpoint: `GET /fe_api/users/?search=<query>`

### 3d. URL router

**File:** `config/urls.py` or wherever `fe_api` router is registered

Verify `UserViewSet` is registered in the `fe_api` router. (It currently is,
under `users`.)

---

## Part 4 — Frontend: `UserListItem` Svelte Component

**File:** `frontend/components/UserListItem.svelte` (new)

Displays a single user in the dropdown list. Modelled after `TeamListItem.svelte`.

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

Add `User` type to `frontend/types.ts` (or wherever org/team types live):

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

## Part 5 — Frontend: `UserSelect` Svelte Component

**File:** `frontend/components/UserSelect.svelte` (new)

A multi-select widget that:

- Fetches users via `/fe_api/users/?search=[query]`
- Detects email-like input and injects a synthetic "invite by email" option
- Shows selections as chips (user chip vs email chip styled differently)
- Emits a list of `{ type: "user", id: number } | { type: "email", email: string }`

Rough structure (Svelte 5, Svelecte):

```svelte
<script lang="ts">
  import type { User } from "@/types";

  import Svelecte from "svelecte";
  import UserListItem from "./UserListItem.svelte";

  type Selection =
    | { type: "user"; id: number; username: string; name: string; avatar_url: string }
    | { type: "email"; email: string };

  let selections: Selection[] = $state([]);
  const fetchProps: RequestInit = { credentials: "include" };

  function fetchCallback(resp: { results: User[] }, query: string): (User | { type: "email"; email: string })[] {
    const users = resp.results;
    const isEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(query);
    const alreadyHasEmail = users.some((u: any) => u.email === query);
    if (isEmail && !alreadyHasEmail) {
      return [...users, { type: "email", email: query, name: query, id: `email:${query}` }];
    }
    return users;
  }
</script>

<Svelecte
  multiple
  name="invitees"
  placeholder="Search users or enter an email…"
  bind:value={selections}
  valueAsObject
  labelField="name"
  fetch="/fe_api/users/?search=[query]"
  {fetchCallback}
  {fetchProps}
  lazyDropdown={false}
>
  {#snippet option(item)}
    {#if item.type === "email"}
      <div class="email-option">Invite <strong>{item.email}</strong> by email</div>
    {:else}
      <UserListItem user={item} />
    {/if}
  {/snippet}

  {#snippet selection(selectedOptions, bindItem)}
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

## Part 6 — Frontend: Wire Into "Invite Members" Form

Progressive enhancement: the form keeps its Django `method="POST"` as a no-JS
fallback. When JS is available, submission is intercepted and each invitation is
posted individually to `POST /fe_api/invitations/` with inline feedback.

### 6a. Template

**File:** `squarelet/templates/organizations/organization_managemembers.html`

Replace the existing `<input type="email" name="emails" multiple ...>` with:

- A `<div id="user-select"></div>` mount point for the `UserSelect` component
- A plain `<input type="email" name="emails">` fallback beneath it (visible only
  when JS is absent, hidden via CSS once the component mounts)

Add `data-org-id="{{ organization.pk }}"` to the form element so the TS
layer can include the org's integer pk in the REST POST body.

### 6b. TypeScript

**File:** `frontend/views/organization_managemembers.ts`

Mount `UserSelect` onto `#user-select`. Intercept the form's `submit` event and
POST each selection to `POST /fe_api/invitations/`, then show inline feedback
without a full page reload.

```typescript
import { mount } from "svelte";
import UserSelect from "@/components/UserSelect.svelte";
import { showAlert } from "../alerts";

type Selection =
  | { type: "user"; id: number; email: string }
  | { type: "email"; email: string };

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
      selections.map((sel) =>
        fetch("/fe_api/invitations/", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify({
            organization: orgId,
            email: sel.email,
            user: sel.type === "user" ? sel.id : null,
            role: parseInt(role),
            request: false,
          }),
        }).then((r) => {
          if (!r.ok) throw r;
          return r;
        }),
      ),
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

### 6c. Backend: `InvitationViewSet.perform_create`

**File:** `squarelet/organizations/fe_api/viewsets.py`

`perform_create` currently saves but never sends the invitation email. Fix this:

```python
def perform_create(self, serializer):
    invitation = serializer.save()
    invitation.send()
```

The org's integer `pk` is passed via `data-org-id` on the form element (see 6a).
The `InvitationSerializer` already accepts `organization` as a pk field — no
serializer changes needed.

### 6d. Django POST fallback

**File:** `squarelet/organizations/views/members.py`

No changes needed. The existing `_handle_add_member` / `AddMemberForm` path
handles the no-JS fallback: a plain email address typed into the fallback input
submits as `name="emails"` to the Django view exactly as before.

---

## Part 7 — Tests

### Backend tests

**Files:**

- `squarelet/users/tests/test_models.py` — test `hidden` transitions (signal fires,
  field updates correctly)
- `squarelet/users/tests/test_api.py` (or new `squarelet/users/fe_api/tests/`) —
  test `GET /fe_api/users/?search=` with hidden/private/public users
- `squarelet/organizations/tests/test_api.py` (or `fe_api/tests/`) —
  test `POST /fe_api/invitations/` sends the invitation email, handles
  duplicate/already-member cases

### Frontend tests

Not in scope for this plan (no existing frontend tests in the codebase).

---

## File Change Summary

| File                                                                | Change                                                      |
| ------------------------------------------------------------------- | ----------------------------------------------------------- |
| `squarelet/organizations/models/organization.py`                    | Add `hidden` BooleanField                                   |
| `squarelet/organizations/migrations/XXXX_add_hidden.py`             | New migration                                               |
| `squarelet/organizations/querysets.py`                              | Change `create_individual` default `private=True` → `False` |
| `squarelet/users/signals.py`                                        | Add signals to set `hidden=False` on email verify / payment |
| `squarelet/users/forms.py`                                          | Add `private` field to `UserUpdateForm`                     |
| `squarelet/users/views.py`                                          | Save `private` to `individual_organization` in update view  |
| `squarelet/users/managers.py`                                       | Add `get_searchable(user)` queryset method                  |
| `squarelet/users/fe_api/serializers.py`                             | Add `UserSearchSerializer`                                  |
| `squarelet/users/fe_api/viewsets.py`                                | Add search, filter, `get_searchable` to `UserViewSet`       |
| `squarelet/organizations/fe_api/viewsets.py`                        | Call `invitation.send()` in `perform_create`                |
| `squarelet/templates/users/user_form.html`                          | (likely no change; field renders automatically)             |
| `squarelet/templates/organizations/organization_managemembers.html` | Replace email input with `#user-select` mount point         |
| `frontend/components/UserListItem.svelte`                           | New component                                               |
| `frontend/components/UserSelect.svelte`                             | New component                                               |
| `frontend/views/organization_managemembers.ts`                      | Mount `UserSelect`, intercept submit, POST to REST API      |
| `frontend/types.ts`                                                 | Add `User` interface                                        |

---

## Open Questions / Decisions Needed

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
