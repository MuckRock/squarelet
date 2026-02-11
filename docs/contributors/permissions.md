# Custom Permissions

Squarelet uses a dual-backend permission system that combines [django-rules](https://github.com/dfunckt/django-rules) for dynamic, object-level checks with Django's built-in `ModelBackend` for database-assigned permissions. When `user.has_perm()` is called, Django checks every backend in `AUTHENTICATION_BACKENDS` and grants access if **any** backend returns `True`.

```python
# config/settings/base.py
AUTHENTICATION_BACKENDS = [
    "rules.permissions.ObjectPermissionBackend",  # django-rules (dynamic)
    "django.contrib.auth.backends.ModelBackend",  # DB-assigned (User/Group)
    ...
]
```

This means a single permission can be granted in two ways:

- **Implicitly** by a rules predicate (e.g. "org admins always have this").
- **Explicitly** by assigning the permission to a User or Group in the database.

## Why permission checks require two calls

Django's `ModelBackend` has a limitation: when you pass an object to `has_perm()`, it **ignores DB-assigned permissions entirely**. This means a single `has_perm()` call can never check both backends:

| Call | `ObjectPermissionBackend` (django-rules) | `ModelBackend` (DB-assigned) |
|---|---|---|
| `user.has_perm(perm, obj)` | Evaluates the predicate with the object | **Skipped** — returns `False` without checking the DB |
| `user.has_perm(perm)` | Evaluates the predicate *without* an object | Checks `user_permissions` and `Group` assignments |

Because of this, any code that needs to respect **both** backends must make two separate calls:

```python
user.has_perm(perm, obj) or user.has_perm(perm)
```

The first call lets django-rules evaluate the predicate against the object (e.g. "is this user an admin of *this* org?"). The second call lets `ModelBackend` check whether the user was explicitly granted the permission in the database (e.g. via `user.user_permissions.add(...)` or a `Group`).

This pattern is safe only because our rules predicates use `@deny_if_not_obj` (see [Predicate decorators](#predicate-decorators-deny_if_not_obj-vs-skip_if_not_obj) below), which makes the rules backend return `False` — not `None` — when no object is provided. Without that decorator, the no-object call could produce false positives.

You'll see this pattern in two places:

- **`OrganizationPermissionMixin`** (`squarelet/organizations/mixins.py`) — for gating entire views.
- **`Detail._has_perm()`** (`squarelet/organizations/views/detail.py`) — for computing per-permission context variables within a single view.

There is an open issue to resolve this through a custom ModelBackend subclass:  [#586](https://github.com/MuckRock/squarelet/issues/586).

## How to add a new permission

The steps below use `can_manage_members` as a concrete example.

### 1. Declare the permission on the model

Add a tuple to `Meta.permissions` so Django creates a `Permission` row during the next migration.

```python
# squarelet/organizations/models/organization.py
class Organization(Model):
    ...
    class Meta:
        permissions = (
            ("merge_organization", "Can merge organizations"),
            ("can_manage_members", "Can manage organization members"),
        )
```

Then generate and apply the migration:

```bash
inv manage "makemigrations organizations"
inv manage "migrate"
```

### 2. Define a rules predicate

In the appropriate rules file, register the permission with `add_perm`. Predicates are composable with `&` (and), `|` (or), and `~` (not).

```python
# squarelet/organizations/rules/organizations.py
from rules import add_perm, is_authenticated

add_perm("organizations.can_manage_members", is_authenticated & is_admin)
```

`is_admin` is a custom predicate decorated with `@deny_if_not_obj` (in `squarelet/core/rules.py`), which returns `False` when called without an object. This ensures that `has_perm(perm)` without an object safely denies access instead of producing false positives -- see [Predicate decorators: `deny_if_not_obj` vs `skip_if_not_obj`](#predicate-decorators-deny_if_not_obj-vs-skip_if_not_obj) below.

### 3. Gate a view with `OrganizationPermissionMixin`

`OrganizationPermissionMixin` (in `squarelet/organizations/mixins.py`) extends Django's `PermissionRequiredMixin` to check the permission against the organization object. It tries two paths:

1. **Object-level**: `user.has_perm(perm, org)` -- evaluated by django-rules.
2. **DB-assigned**: `user.has_perm(perm)` -- evaluated by `ModelBackend` (Django's `ModelBackend` skips DB-assigned perms when an object is passed, so both calls are needed). This is safe because `deny_if_not_obj` makes the rules backend return `False` when no object is provided.

```python
# squarelet/organizations/views/members.py
from squarelet.organizations.mixins import OrganizationPermissionMixin

class ManageMembers(OrganizationPermissionMixin, DetailView):
    permission_required = "organizations.can_manage_members"
    queryset = Organization.objects.filter(individual=False)
```

Authenticated users without the permission receive a **403**. Anonymous users are **redirected to login**.

### 4. Check the permission in a template

Load the `rules` template tags and use `{% has_perm %}` to evaluate the permission against the current user and object.

```html+django
{% load rules %}

{% has_perm "organizations.can_manage_members" user organization as can_manage_members %}

{% if can_manage_members %}
  <a href="{% url 'organizations:manage-members' organization.slug %}">
    Manage members
  </a>
{% endif %}
```

`{% has_perm %}` calls `user.has_perm(perm, obj)` under the hood, so the django-rules predicate is evaluated with the organization as the object.

### 5. Write tests

Follow the TDD pattern established in `squarelet/organizations/tests/test_permissions.py`. Cover three layers:

**Rule-level** -- verify `user.has_perm()` returns the expected boolean:

```python
def test_admin_has_can_manage_members(self, organization_factory, user_factory):
    admin = user_factory()
    org = organization_factory(admins=[admin])
    assert admin.has_perm("organizations.can_manage_members", org)

def test_member_lacks_can_manage_members(self, organization_factory, user_factory):
    member = user_factory()
    org = organization_factory(users=[member])
    assert not member.has_perm("organizations.can_manage_members", org)
```

**View-level** -- verify the mixin enforces access:

```python
def test_manage_members_view_denied_for_member(self, rf, organization_factory, user_factory):
    member = user_factory()
    org = organization_factory(users=[member])
    with pytest.raises(PermissionDenied):
        self.call_view(rf, member, slug=org.slug)
```

**DB-assigned** -- verify that explicitly assigned permissions work:

```python
def test_staff_with_db_perm_has_can_manage_members(self, user_factory):
    user = user_factory()
    ct = ContentType.objects.get_for_model(Organization)
    perm = Permission.objects.get(codename="can_manage_members", content_type=ct)
    user.user_permissions.add(perm)
    user = type(user).objects.get(pk=user.pk)  # clear cached perms
    assert user.has_perm("organizations.can_manage_members")
```

## Predicate decorators: `deny_if_not_obj` vs `skip_if_not_obj`

Both decorators live in `squarelet/core/rules.py` and handle the case where a predicate is called without an object (i.e. `has_perm(perm)` with no `obj`).

- **`deny_if_not_obj`** returns `False` -- the predicate **denies** access. This is the safe default and should be used for all new predicates. Organization rules already use this decorator.
- **`skip_if_not_obj`** returns `None` -- the predicate is **skipped**. The rules `&` operator treats `None` as "skip this predicate", which can produce false positives. For example, `is_authenticated & is_admin` would evaluate to `True` for any authenticated user when `is_admin` is skipped. This decorator is **deprecated** and should be migrated to `deny_if_not_obj`.

Because organization predicates use `deny_if_not_obj`, `OrganizationPermissionMixin` can safely call `has_perm(perm)` without an object as a fallback for DB-assigned permissions:

```python
# From OrganizationPermissionMixin.has_permission
return all(user.has_perm(perm, obj) or user.has_perm(perm) for perm in perms)
```

When adding a new permission, always use `@deny_if_not_obj` on predicates that require an object.

## Quick-reference checklist

- [ ] Add permission to `Model.Meta.permissions`
- [ ] Run `makemigrations` + `migrate`
- [ ] Register predicate with `add_perm()` in the rules file (use `@deny_if_not_obj` on predicates that need an object)
- [ ] Use `OrganizationPermissionMixin` in the view (or call `has_perm` directly)
- [ ] Use `{% has_perm %}` in templates
- [ ] Write rule-level, view-level, and DB-assigned tests
