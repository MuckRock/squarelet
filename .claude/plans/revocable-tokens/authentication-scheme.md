# Authentication Scheme: How Squarelet Authenticates Connected Applications

## Overview

Squarelet acts as a **centralized identity provider** using **OpenID Connect (OIDC)** via the `oidc_provider` Django package. Both DocumentCloud and MuckRock are OIDC clients that delegate authentication to Squarelet.

## Squarelet (Identity Provider)

### OIDC Provider Configuration
- **Package**: `oidc_provider` (django-oidc-provider)
- **Endpoint**: `/openid/` (standard OIDC discovery)
- **Token endpoint**: `/openid/jwt` — custom override that issues **JWT tokens** via `rest_framework_simplejwt` instead of standard OIDC opaque tokens
- **Settings** (`config/settings/base.py`):
  - `OIDC_GRANT_TYPE_PASSWORD_ENABLE = True` — **This is the security concern.** It enables the Resource Owner Password Credentials (ROPC) grant, allowing direct username/password exchange for tokens via API.
  - `OIDC_SESSION_MANAGEMENT_ENABLE = True`
  - `OIDC_SKIP_CONSENT_EXPIRE = 180` (days)
  - Custom userinfo: `squarelet.users.oidc.userinfo`
  - Custom scope claims: `squarelet.users.oidc.CustomScopeClaims`

### OIDC Scopes Served
- `openid` (standard)
- `uuid` — user's UUID
- `organizations` — user's organization memberships (serialized)
- `preferences` — user preferences (e.g., `use_autologin`)
- `bio` — user bio

### Token Flow (Custom)
The custom `TokenEndpoint` in `squarelet/oidc/views.py`:
1. Receives an authorization code
2. Creates an OIDC token via `oidc_provider`
3. **Also creates a JWT** via `rest_framework_simplejwt.tokens.RefreshToken.for_user()`
4. Returns both the JWT access/refresh tokens AND the OIDC id_token

### Standalone JWT Endpoints (SimpleJWT)
In addition to the OIDC token flow, Squarelet exposes direct JWT endpoints:
- `api/token/` — `TokenObtainPairView` (username/password → JWT pair) — **another password-grant vector**
- `api/refresh/` — `TokenRefreshView` (refresh token → new access token)

SimpleJWT config (`config/settings/base.py`):
```python
SIMPLE_JWT = {
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "ALGORITHM": "RS256",
    "AUDIENCE": ["squarelet", "muckrock", "documentcloud"],
    "ISSUER": ["squarelet"],
    "USER_ID_FIELD": "individual_organization_id",
    "SIGNING_KEY": "",   # Set dynamically from RSAKey in DB
    "VERIFYING_KEY": "", # Set dynamically from RSAKey in DB
}
```

The RSA key is shared between OIDC and SimpleJWT — loaded from `oidc_provider.RSAKey` at app startup in `squarelet/users/apps.py`.

### Service-to-Service Token Endpoints
Squarelet also has service-to-service endpoints protected by OIDC scope permissions (`ScopePermission`):
- `RefreshTokenViewSet` (`/api/refresh_tokens/{uuid}/`) — generates JWT pair for a user, can embed `permissions` in the payload. Requires `read_auth_token` scope.
- `UrlAuthTokenViewSet` (`/api/url_auth_tokens/{uuid}/`) — generates sesame one-time login tokens. Requires `read_auth_token` scope.

These are used by MuckRock/DocumentCloud to get tokens on behalf of users after OIDC auth.

### Client Registration
- OIDC clients are `oidc_provider.Client` model instances
- Extended by `squarelet.oidc.models.ClientProfile` (adds `webhook_url` and `source`)
- Clients can receive **cache invalidation webhooks** signed with HMAC (client_secret as key)

### REST Framework Auth on Squarelet Itself
```python
"DEFAULT_AUTHENTICATION_CLASSES": (
    "squarelet.oidc.authentication.OidcOauth2Authentication",  # OIDC access token
    "rest_framework.authentication.SessionAuthentication",      # Django sessions
),
```

### Cache Invalidation System
When user/org data changes on Squarelet, it sends HMAC-signed webhooks to registered OIDC clients via `CacheInvalidationSenderMiddleware`. Connected apps receive these and pull fresh data.

---

## DocumentCloud (OIDC Client)

### Authentication with Squarelet
- **Package**: `squarelet-auth` (v0.1.14, pip package `squarelet-auth`)
- **Backend**: `squarelet_auth.backends.SquareletBackend` — extends `social_core.backends.open_id_connect.OpenIdConnectAuth`
- **OAuth flow**: Standard OIDC Authorization Code flow via `python-social-auth`
- **Scopes requested**: `["uuid", "organizations", "preferences"]`
- **Extra args**: `{"intent": "documentcloud"}`

### Social Auth Pipeline
```python
SOCIAL_AUTH_PIPELINE = (
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.auth_allowed",
    "social_core.pipeline.social_auth.social_user",
    "social_core.pipeline.user.get_username",
    "squarelet_auth.pipeline.associate_by_uuid",  # Match users by UUID
    "squarelet_auth.pipeline.save_info",           # Update user info from Squarelet
    "squarelet_auth.pipeline.save_session_data",   # Store session_state & id_token
    "social_core.pipeline.social_auth.associate_user",
    "social_core.pipeline.social_auth.load_extra_data",
    "social_core.pipeline.user.user_details",
)
```

### API Authentication (REST Framework)
```python
"DEFAULT_AUTHENTICATION_CLASSES": (
    "rest_framework.authentication.SessionAuthentication",          # Browser sessions
    "rest_framework_simplejwt.authentication.JWTAuthentication",   # JWT tokens
    "documentcloud.core.authentication.ProcessingTokenAuthentication",  # Internal processing
),
```

### JWT Configuration
```python
SIMPLE_JWT = {
    "ALGORITHM": "RS256",
    "VERIFYING_KEY": env.str("JWT_VERIFYING_KEY", multiline=True),
    "AUDIENCE": ["documentcloud"],
    "USER_ID_FIELD": "uuid",
}
```
- Uses **RS256** (asymmetric) — Squarelet signs with private key, DocumentCloud verifies with public key
- JWTs issued by Squarelet's custom token endpoint are directly usable for DocumentCloud API access
- User identification via `uuid` field

### Key Insight for Token Implementation
DocumentCloud uses **JWT tokens issued by Squarelet** for API auth. The JWT is verified using a shared public key. This means any new token system on Squarelet needs to either:
1. Issue JWTs that DocumentCloud can verify (preferred, no DC changes needed), OR
2. Require DocumentCloud to add a new authentication backend

---

## MuckRock (OIDC Client)

### Authentication with Squarelet
- **Backend**: `muckrock.accounts.backends.SquareletBackend` — extends `OpenIdConnectAuth` (copied/forked, not using `squarelet-auth` package)
- **Includes password grant support**: The backend has explicit code to handle ROPC password grant flow
- **Scopes requested**: `["uuid", "organizations", "preferences"]`
- **Extra args**: `{"intent": "muckrock"}`
- Also uses `sesame.backends.ModelBackend` for magic login links

### API Authentication (REST Framework)
```python
"DEFAULT_AUTHENTICATION_CLASSES": (
    "rest_framework.authentication.TokenAuthentication",    # DRF Token (authtoken)
    "rest_framework.authentication.SessionAuthentication",  # Browser sessions
),
```

### Token System
- Uses Django REST Framework's built-in `rest_framework.authtoken` — **simple, non-expiring, one-per-user tokens**
- Token is shown on the user's MuckRock profile page: `Token.objects.get_or_create(user=self.user)`
- This is the existing token that needs to be replaced with revocable tokens

### Key Insight for Token Implementation
MuckRock uses DRF's `TokenAuthentication` — a simple model-backed token. These tokens:
- Never expire
- Cannot be scoped
- One per user (get_or_create pattern)
- Are created lazily when viewing the profile page

This is the primary API auth mechanism that needs replacement.

---

## Summary of Current Auth Flows

| Flow | Squarelet | DocumentCloud | MuckRock |
|------|-----------|--------------|----------|
| Browser login | Django sessions + allauth | OIDC → Squarelet → session | OIDC → Squarelet → session |
| API auth | OIDC OAuth2 token | JWT (from Squarelet) or session | DRF Token or session |
| Token issuance | OIDC token endpoint (issues JWT) | N/A (uses Squarelet JWTs) | DRF authtoken (auto-created) |
| Password grant | Enabled (ROPC) | N/A | Backend supports it |
| 2FA | allauth MFA (TOTP + WebAuthn) | N/A (deferred to Squarelet) | N/A (deferred to Squarelet) |

## Security Concerns (Why This Issue Exists)

1. **ROPC password grant is enabled** (`OIDC_GRANT_TYPE_PASSWORD_ENABLE = True`) — anyone with username/password can get a token via API, completely bypassing 2FA
2. **Standalone JWT endpoint** (`api/token/`) also accepts username/password directly — another 2FA bypass vector
3. **MuckRock tokens never expire** and are not scoped
4. **No centralized token management** — MuckRock tokens are managed in MuckRock, DC JWTs are issued via OIDC flow
5. **`rest_framework.authtoken` is a dead dependency in Squarelet** — listed in `INSTALLED_APPS` but never used in Squarelet's own code (it's used by MuckRock separately)
6. The goal is to replace all of this with **user-managed, revocable, scoped tokens** issued from Squarelet's Account → Security section
