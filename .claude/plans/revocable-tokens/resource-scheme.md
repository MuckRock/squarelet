# Resource Scheme: Mapping Application Resources for Scoped Tokens

## Resources Per Application

### DocumentCloud

DocumentCloud exposes the following user-manageable resources via its REST API:

| Resource | Model | ViewSet | Key Operations |
|----------|-------|---------|----------------|
| **Documents** | `documents.Document` | `DocumentViewSet` | CRUD, bulk create/update, search, upload, process |
| **Notes** | `documents.Note` | `NoteViewSet` | CRUD (annotations on documents) |
| **Projects** | `projects.Project` | `ProjectViewSet` | CRUD, manage memberships, manage collaborations |
| **Sections** | `documents.Section` | `SectionViewSet` | CRUD (document sections/bookmarks) |
| **Saved Searches** | `documents.SavedSearch` | `SavedSearchViewSet` | CRUD |
| **Add-Ons** | `addons.AddOn` | `AddOnViewSet` | CRUD, run add-ons |
| **Add-On Runs** | `addons.AddOnRun` | `AddOnRunViewSet` | CRUD, track runs |

**Secondary/read-heavy resources** (less likely to need write scoping):
- Users (read-only viewset)
- Organizations (read-only viewset)
- Entities/Entity Occurrences (bulk create for NLP results)
- Redactions (create-only)
- Modifications (create-only)

**Recommended token scopes for DocumentCloud:**
- `documentcloud:documents` — Documents, Notes, Sections (all document-related)
- `documentcloud:projects` — Projects, Memberships, Collaborations
- `documentcloud:addons` — Add-Ons and Add-On Runs
- `documentcloud:saved_searches` — Saved Searches

### MuckRock

MuckRock exposes the following user-manageable resources via its REST API:

| Resource | Model | ViewSet(s) | Key Operations |
|----------|-------|------------|----------------|
| **FOIA Requests** | `foia.FOIARequest` | `FOIARequestViewSet` (v1 + v2) | CRUD, file requests, follow up |
| **FOIA Communications** | `foia.FOIACommunication` | `FOIACommunicationViewSet` (v1 + v2) | CRUD (messages on requests) |
| **FOIA Files** | `foia.FOIAFile` | `FOIAFileViewSet` (v2, read-only) | Read files attached to comms |
| **Projects** | `project.Project` | `ProjectViewSet` (v1 + v2) | CRUD |
| **Crowdsource Responses** | `crowdsource.CrowdsourceResponse` | `CrowdsourceResponseViewSet` | Create responses |

**Secondary/read-heavy resources:**
- Users (read-only in v2)
- Organizations (read-only in v2)
- Jurisdictions (read-only in v2, CRUD in v1)
- Agencies (read-only in v2, CRUD in v1)
- Articles/Photos (news viewsets)
- Statistics (read-only)
- Exemptions

**Recommended token scopes for MuckRock:**
- `muckrock:requests` — FOIA Requests, Communications, Files
- `muckrock:projects` — Projects
- `muckrock:crowdsource` — Crowdsource Responses

---

## Modeling Resources in Squarelet

### Current State

Squarelet already has:
- **`Service` model** (`squarelet/services/models.py`) — represents connected applications (MuckRock, DocumentCloud, etc.) with `slug`, `name`, `icon`, `description`, `provider_name`, `base_url`
- **`oidc_provider.Client`** — OIDC client representing each application
- **`Entitlement` model** (`squarelet/organizations/models/payment.py`) — grants access to services, has a `resources` JSONField for metadata and links to an `oidc_provider.Client`

The `Service` model is currently lightweight and not linked to `oidc_provider.Client`. The `Entitlement` model already has a concept of resources but as free-form JSON.

### Proposed Data Model

#### New `Resource` Model

Create a new `Resource` model in the `services` app to represent individual API resource categories:

```python
# squarelet/services/models.py

class Resource(models.Model):
    """A resource category within a connected service that can be scoped for API tokens."""

    service = models.ForeignKey(
        "services.Service",
        on_delete=models.CASCADE,
        related_name="resources",
        help_text="The service this resource belongs to",
    )
    slug = models.SlugField(
        max_length=100,
        help_text="Machine-readable identifier (e.g., 'documents', 'requests')",
    )
    name = models.CharField(
        max_length=255,
        help_text="Human-readable name (e.g., 'Documents', 'FOIA Requests')",
    )
    description = models.TextField(
        blank=True,
        help_text="Description of what this resource grants access to",
    )

    class Meta:
        unique_together = [("service", "slug")]
        ordering = ["service", "name"]

    def __str__(self):
        return f"{self.service.name}: {self.name}"

    @property
    def scope_name(self):
        """Full scope identifier, e.g. 'documentcloud:documents'"""
        return f"{self.service.slug}:{self.slug}"
```

#### Link `Service` to `oidc_provider.Client`

Add a ForeignKey from `Service` to `oidc_provider.Client` to tie the service registry to the OIDC infrastructure:

```python
# Add to Service model
client = models.OneToOneField(
    "oidc_provider.Client",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="service",
    help_text="OIDC client associated with this service",
)
```

### Initial Resource Data (Fixture or Migration)

The initial resources would be seeded via a data migration or fixture:

```python
# DocumentCloud resources
("documentcloud", "documents", "Documents", "Access to documents, notes, and sections"),
("documentcloud", "projects", "Projects", "Access to projects and collaborations"),
("documentcloud", "addons", "Add-Ons", "Access to add-ons and their runs"),
("documentcloud", "saved_searches", "Saved Searches", "Access to saved searches"),

# MuckRock resources
("muckrock", "requests", "Requests", "Access to FOIA requests, communications, and files"),
("muckrock", "projects", "Projects", "Access to projects"),
("muckrock", "crowdsource", "Crowdsource", "Access to crowdsource responses"),
```

### How This Connects to Tokens

The `Resource` model feeds into the token system:
- When creating a token, the user selects which resources the token should have access to
- The token stores its allowed resources as a M2M relationship
- When a connected application authenticates a request with a token, it checks the token's resource scopes

### How Connected Applications Verify Scopes

Two approaches:

**Option A: Encode scopes in JWT claims** (preferred for DocumentCloud)
- When issuing a token, include a `scopes` claim in the JWT payload
- DocumentCloud already verifies JWTs with RS256; it just needs to read the `scopes` claim
- Minimal changes to DocumentCloud

**Option B: Scope verification API endpoint on Squarelet**
- Connected applications call a Squarelet API to verify token scopes
- More round-trips but more flexible
- Better for MuckRock since it currently uses opaque tokens

**Option C: Hybrid** (recommended)
- Encode scopes in JWT for DocumentCloud (stateless verification)
- For MuckRock, replace DRF `TokenAuthentication` with a custom backend that either:
  - Verifies JWTs (if we unify on JWT), or
  - Calls Squarelet to validate opaque tokens

### Relationship to Existing `Entitlement`

The `Resource` model is distinct from `Entitlement`:
- **`Entitlement`** = what an organization's plan grants access to (billing concern)
- **`Resource`** = what a token can be scoped to (authorization concern)

They may overlap (e.g., an org needs the DocumentCloud entitlement to access documents), but they serve different purposes. Token scope should be a subset of what the user's organization entitlements allow.
