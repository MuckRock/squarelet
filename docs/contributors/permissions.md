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

## How `add_perm_with_db_check` unifies both backends

Django's `ModelBackend` has a limitation: when you pass an object to `has_perm()`, it _ignores DB-assigned permissions entirely_. To work around this without requiring two separate `has_perm()` calls, we use the `add_perm_with_db_check` helper (in `squarelet/core/rules.py`).

`add_perm_with_db_check` registers a rules predicate that combines the dynamic check with a direct DB lookup:

```python
# squarelet/core/rules.py
def has_db_perm(perm):
    @predicate(f"has_db_perm:{perm}")
    def inner(user):
        backend = load_backend("django.contrib.auth.backends.ModelBackend")
        return backend.has_perm(user, perm)
    return inner

def add_perm_with_db_check(perm, pred):
    add_perm(perm, pred | has_db_perm(perm))
```

The resulting rule is `pred | has_db_perm(perm)`, so a single call to `user.has_perm(perm, obj)` will:

1. Evaluate the dynamic predicate with the object (e.g. "is this user an admin of *this* org?").
2. If that fails, check whether the user was explicitly granted the permission in the database (via `user.user_permissions` or a `Group`).

Use `add_perm_with_db_check` for any permission that should be grantable both dynamically (via rules) and explicitly (via the DB). Usually, but not always, DB grants are reserved for granting system-wide permissions to staff roles.

For permissions that are purely DB-assigned with no dynamic rule, pass `always_deny` as the predicate (e.g. `can_review_profile_changes`). This will prevent all access, except for users with DB-assigned permission, while still allowing us to support a single `user.has_perm(perm, obj)` check, like in our  `OrganizationPermissionMixin`.

Use plain `add_perm` for permissions that only need the rules predicate (e.g. `add_organization`, `view_organization`, `delete_organization`) and won't have the permission assed in the DB.

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

### 2. Register the permission with `add_perm_with_db_check`

In the appropriate rules file, register the permission using `add_perm_with_db_check`. This combines the dynamic predicate with a DB-assigned fallback in a single rule. Predicates are composable with `&` (and), `|` (or), and `~` (not).

```python
# squarelet/organizations/rules/organizations.py
from squarelet.core.rules import add_perm_with_db_check

add_perm_with_db_check("organizations.can_manage_members", is_admin)
```

`is_admin` is a custom predicate decorated with `@skip_if_not_obj` (in `squarelet/core/rules.py`), which returns `None` when called without an object. Because `add_perm_with_db_check` uses `|` (or), the `None` from the skipped predicate still allows the `has_db_perm` fallback to run.

### 3. Gate a view with `OrganizationPermissionMixin`

`OrganizationPermissionMixin` (in `squarelet/organizations/mixins.py`) extends Django's `PermissionRequiredMixin` to check the permission against the organization object. Because `add_perm_with_db_check` bakes the DB fallback into the rule itself, the mixin only needs a single `has_perm` call:

```python
# From OrganizationPermissionMixin.has_permission
return all(user.has_perm(perm, obj) for perm in perms)
```

To use the mixin:

```python
# squarelet/organizations/views/members.py
from squarelet.organizations.mixins import OrganizationPermissionMixin

class ManageMembers(OrganizationPermissionMixin, DetailView):
    permission_required = "organizations.can_manage_members"
    queryset = Organization.objects.filter(individual=False)
```

Authenticated users without the permission receive a **403**. Anonymous users are **redirected to login**.

### 4. Check the permission in a template

Load the `rules` template tags and use `{% has_perm %}` to evaluate the permission against the current user and object. This is the preferred way to gate UI elements: use `{% has_perm %}` instead of checking context variables like `is_admin` or `user.is_staff`.

```html+django
{% load rules %}

{% has_perm "organizations.change_organization" user organization as can_change_organization %}
{% has_perm "organizations.can_manage_members" user organization as can_manage_members %}
{% has_perm "organizations.can_view_members" user organization as can_view_members %}
{% has_perm "organizations.can_view_subscription" user organization as can_view_subscription %}
{% has_perm "organizations.can_edit_subscription" user organization as can_edit_subscription %}

{% if can_manage_members %}
  <a href="{% url 'organizations:manage-members' organization.slug %}">
    Manage members
  </a>
{% endif %}
```

`{% has_perm %}` calls `user.has_perm(perm, obj)` under the hood, so the combined rule (dynamic predicate + DB fallback) is evaluated in a single call.

### 5. Check the permission in a view's `get_context_data`

When you need permission-dependent logic in a view (not just gating access), use `user.has_perm(perm, obj)` directly:

```python
# squarelet/organizations/views/detail.py
if user.has_perm("organizations.can_manage_members", org):
    context["pending_requests"] = org.invitations.get_pending_requests()

if user.has_perm("organizations.can_view_members", org):
    context["users"] = users
else:
    context["users"] = admins
```

Avoid ad-hoc role checks like `is_admin or user.is_staff` -- always go through `has_perm` so that both dynamic rules and DB-assigned permissions are respected.

### 6. Write tests

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
def test_db_perm_grants_can_manage_members(self, user_factory, organization_factory):
    user = user_factory()
    org = organization_factory()
    ct = ContentType.objects.get_for_model(Organization)
    perm = Permission.objects.get(codename="can_manage_members", content_type=ct)
    user.user_permissions.add(perm)
    user = type(user).objects.get(pk=user.pk)  # clear cached perms
    assert user.has_perm("organizations.can_manage_members", org)
```

Note: because `add_perm_with_db_check` bakes the DB fallback into the rule, the DB-assigned test passes an `org` object to `has_perm`. The `has_db_perm` predicate within the combined rule checks the DB directly, so this works in a single call.

## The `skip_if_not_obj` decorator

`skip_if_not_obj` lives in `squarelet/core/rules.py` and handles the case where a predicate is called without an object (i.e. `has_perm(perm)` with no `obj`). It returns `None`, which tells the rules `&` and `|` operators to skip the predicate.

```python
@predicate
@skip_if_not_obj
def is_admin(user, organization):
    return organization.has_admin(user)
```

With `add_perm_with_db_check`, this is safe: the combined rule `is_admin | has_db_perm(perm)` will skip `is_admin` (returning `None`) and then evaluate `has_db_perm`, which checks the DB directly.

**Caution**: Do not use `skip_if_not_obj` predicates with plain `add_perm` in a way that could produce false positives. For example, `is_authenticated & is_admin` would evaluate to `True` for any authenticated user when `is_admin` returns `None` (because `&` skips the `None`). The `add_perm_with_db_check` helper avoids this problem by using `|` instead of `&` to compose the DB fallback.

## Quick-reference checklist

- [ ] Add permission to `Model.Meta.permissions`
- [ ] Run `makemigrations` + `migrate`
- [ ] Register permission with `add_perm_with_db_check()` in the rules file
- [ ] Use `OrganizationPermissionMixin` in the view (or call `has_perm` directly)
- [ ] Use `{% has_perm %}` in templates
- [ ] Write rule-level, view-level, and DB-assigned tests
