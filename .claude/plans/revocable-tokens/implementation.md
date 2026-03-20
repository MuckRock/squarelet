# Implementation Plan: Revocable Scoped API Tokens

## Phase 1: Data Models (Squarelet)

### 1.1 Extend the `Service` model

Add a link to `oidc_provider.Client`:

```python
# squarelet/services/models.py — add to Service
client = models.OneToOneField(
    "oidc_provider.Client",
    on_delete=models.SET_NULL,
    null=True, blank=True,
    related_name="service",
)
```

### 1.2 Create the `Resource` model

```python
# squarelet/services/models.py
class Resource(models.Model):
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="resources")
    slug = models.SlugField(max_length=100)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    class Meta:
        unique_together = [("service", "slug")]
        ordering = ["service", "name"]

    @property
    def scope_name(self):
        return f"{self.service.slug}:{self.slug}"
```

### 1.3 Create the `APIToken` model

```python
# squarelet/services/models.py (or a new squarelet/tokens/ app)
import secrets
from django.conf import settings

class APIToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
    )
    name = models.CharField(max_length=255)
    # Store only the hash; the raw token is shown once at creation
    token_hash = models.CharField(max_length=128, unique=True, db_index=True)
    # Prefix for identification without exposing the full token (e.g., "sq_abc1")
    prefix = models.CharField(max_length=10)
    resources = models.ManyToManyField(Resource, blank=True, related_name="tokens")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # null = no expiry
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("user", "name")]
        ordering = ["-created_at"]

    @classmethod
    def generate_token(cls):
        """Generate a random token string. Returns (raw_token, hash, prefix)."""
        raw = f"sq_{secrets.token_urlsafe(32)}"
        hash_ = hashlib.sha256(raw.encode()).hexdigest()
        prefix = raw[:10]
        return raw, hash_, prefix

    @classmethod
    def create_token(cls, user, name, resources=None, expires_at=None):
        """Create a new token. Returns (token_instance, raw_token)."""
        raw, hash_, prefix = cls.generate_token()
        token = cls.objects.create(
            user=user, name=name, token_hash=hash_,
            prefix=prefix, expires_at=expires_at,
        )
        if resources:
            token.resources.set(resources)
        return token, raw

    def verify(self, raw_token):
        return hmac.compare_digest(
            self.token_hash,
            hashlib.sha256(raw_token.encode()).hexdigest()
        )

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return self.is_active and not self.is_expired

    def revoke(self):
        self.is_active = False
        self.save(update_fields=["is_active"])

    def regenerate(self):
        """Revoke this token and create a new one with the same name and scopes."""
        resources = list(self.resources.all())
        self.revoke()
        new_token, raw = APIToken.create_token(
            user=self.user, name=self.name,
            resources=resources, expires_at=self.expires_at,
        )
        return new_token, raw
```

### 1.4 Data migration

Seed `Resource` entries for DocumentCloud and MuckRock, and link existing `Service` objects to their `oidc_provider.Client` counterparts.

---

## Phase 2: Token Management UI (Squarelet)

### 2.1 Add to Account → Security section

The Security section in `squarelet/templates/users/user_detail.html` already has:
- Automatic login links toggle
- Password change link
- Two-factor authentication management

Add a new **"API Tokens"** subsection below the MFA section.

### 2.2 UI Requirements

**Token list view** (inline in Security section):
- Table showing: Name, Prefix (masked), Resources/Scopes, Created, Last Used, Actions
- Actions: Regenerate, Revoke (with confirmation)

**Create token form** (modal or inline expansion):
- Token name (text input)
- Resource selection (checkboxes grouped by service)
- Optional expiration date
- Submit → shows the raw token **once** in a copyable field with a warning that it won't be shown again

**Regenerate flow:**
- Confirm dialog explaining the old token will stop working
- Shows new raw token once

**Revoke flow:**
- Confirm dialog
- Token removed from list (or marked as revoked)

### 2.3 Views

Create new views (or extend `UserDetailView`) in `squarelet/users/views.py`:
- `POST /users/<username>/tokens/` — create token
- `POST /users/<username>/tokens/<id>/regenerate/` — regenerate
- `POST /users/<username>/tokens/<id>/revoke/` — revoke (or DELETE)

Or use DRF viewset on Squarelet's API if preferred.

---

## Phase 3: Token Verification API (Squarelet)

Connected applications need to verify tokens. Two options:

### Option A: JWT-based tokens (stateless)

When creating a token, Squarelet could issue a JWT signed with its private key that encodes:
```json
{
  "sub": "<user-uuid>",
  "token_id": "<token-id>",
  "scopes": ["documentcloud:documents", "documentcloud:projects"],
  "iat": 1234567890,
  "exp": null
}
```

**Pros**: No round-trip to Squarelet for verification; DocumentCloud already has JWT verification.
**Cons**: Can't be revoked instantly (must wait for expiry or check a revocation list); long-lived JWTs are problematic.

### Option B: Opaque tokens + verification endpoint (stateful)

Add a Squarelet API endpoint:
```
POST /api/tokens/verify/
Authorization: Bearer <client-secret or HMAC>
Body: { "token": "sq_..." }
Response: { "valid": true, "user_uuid": "...", "scopes": [...] }
```

**Pros**: Instant revocation; simple token format.
**Cons**: Every API request requires a round-trip to Squarelet; adds latency and a SPOF.

### Option C: Hybrid (recommended)

- Issue **short-lived JWTs** (e.g., 5–15 min) that encode scopes
- Connected apps verify JWTs locally (no round-trip)
- Connected apps cache/refresh by calling Squarelet when JWT expires
- Revocation takes effect within the JWT's TTL
- The `sq_` opaque token is exchanged for a JWT at a Squarelet endpoint

**Exchange endpoint:**
```
POST /api/tokens/exchange/
Body: { "token": "sq_..." }
Response: { "access_token": "<jwt>", "expires_in": 900 }
```

This is similar to how the current OIDC flow works but initiated by the user's API client rather than a browser redirect.

---

## Phase 4: Connected Application Changes

### 4.1 DocumentCloud

**Minimal changes needed** if using JWT approach:
- Add a custom DRF authentication class that:
  1. Accepts `Authorization: Bearer sq_...` tokens
  2. Exchanges them with Squarelet for a JWT (cached)
  3. Verifies JWT as it already does
  4. Checks scopes against the requested resource
- Add scope-checking permission class or middleware
- The existing `JWTAuthentication` can be extended to handle scope verification

### 4.2 MuckRock

**Replace `rest_framework.authtoken.TokenAuthentication`:**
- Add a custom authentication class that:
  1. Accepts `Authorization: Token sq_...` header
  2. Calls Squarelet's token verification/exchange endpoint
  3. Caches the result for the JWT's TTL
  4. Returns the authenticated user
- Add scope-checking permission class
- Migration path: continue accepting old DRF tokens during a transition period, then deprecate

### 4.3 Migration Path for Existing MuckRock Tokens

1. Keep old `TokenAuthentication` active alongside new auth for a deprecation period
2. Show deprecation warnings in API responses for old tokens
3. Prompt users to create new tokens on their Squarelet account
4. After deprecation period, disable old tokens

---

## Phase 5: Disable Password Grant

Once revocable tokens are in place:
1. Set `OIDC_GRANT_TYPE_PASSWORD_ENABLE = False` in Squarelet settings
2. Remove password grant code from MuckRock's `SquareletBackend`
3. All API access now requires either:
   - A browser session (from OIDC login with 2FA), or
   - A revocable scoped token (issued via the UI after 2FA login)

---

## Implementation Order

1. **Models** — `Resource`, `APIToken`, extend `Service` (Squarelet)
2. **Admin** — Register new models for initial data management
3. **Token management views + UI** — Security section in user detail (Squarelet)
4. **Token exchange/verification endpoint** — API on Squarelet
5. **DocumentCloud integration** — Custom auth class + scope checking
6. **MuckRock integration** — Replace TokenAuthentication + scope checking
7. **Migration** — Deprecate old MuckRock tokens, disable password grant
8. **Testing** — End-to-end token lifecycle tests

## Files to Create/Modify in Squarelet

| File | Action | Description |
|------|--------|-------------|
| `squarelet/services/models.py` | Modify | Add `Resource` model, extend `Service` with `client` FK |
| `squarelet/services/admin.py` | Modify | Register `Resource`, inline on `Service` |
| `squarelet/services/migrations/XXXX_*.py` | Create | Schema + data migrations |
| `squarelet/tokens/` (new app) or extend `services` | Create | `APIToken` model, views, serializers |
| `squarelet/templates/users/user_detail.html` | Modify | Add API Tokens section to Security |
| `squarelet/users/views.py` | Modify | Add token CRUD views |
| `squarelet/users/urls.py` | Modify | Add token management URL patterns |
| `config/settings/base.py` | Modify | Add new app to `INSTALLED_APPS` |

## Open Questions

1. **Token format**: Should the raw token be a simple opaque string (`sq_<random>`) or a JWT? Opaque is simpler for the user and more secure (hash stored server-side).
2. **Read vs Write scopes**: Should each resource have separate read/write scopes, or just a single access scope? Per the issue discussion, per-resource seems sufficient without read/write granularity.
3. **Rate limiting**: Should tokens have per-token rate limits?
4. **Organization tokens**: Should tokens be per-user or can organizations issue tokens? Starting with per-user is simpler.
5. **Token exchange caching**: How long should connected apps cache the JWT from a token exchange? 5-15 minutes seems reasonable.
