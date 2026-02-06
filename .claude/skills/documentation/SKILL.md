---
name: documentation
description: Create or update product documentation for end-users
---

# Product Documentation Authoring Skill

Use this skill when the user wants to create, update, or review product documentation for MuckRock Accounts end-users. (Squarelet is the codename for MuckRock Accounts)

---

## 1. Documentation Procedure

Follow this workflow when writing or updating product documentation:

### Step 1: Understand the User Need
- Identify what feature or workflow needs documentation
- Consider who will read this (journalists, researchers, organization admins)
- Determine the user's goal: What are they trying to accomplish?

### Step 2: Research the Feature
- Use the application to understand the user experience
- Review templates in `squarelet/templates/` to understand UI flows
- Check frontend components in `frontend/views/` for user-facing features
- Note any error messages, confirmations, or edge cases users might encounter

### Step 3: Outline the Content
- Start with the user's goal as the headline
- Break down into clear, sequential steps
- Identify prerequisites (account type, permissions, settings)
- Note common questions or pitfalls

### Step 4: Write for the User
- Use plain language, not technical jargon
- Include screenshots where helpful (note locations for screenshots)
- Write actionable steps, not descriptions
- Anticipate and answer "what if" questions

### Step 5: Save and Organize
- Save as Markdown in `docs/product/`
- Use descriptive filenames: `managing-team-members.md`
- Update the index when adding new pages

---

## 2. Style Rules

### Voice and Tone
- **Friendly but professional**: Write like a helpful colleague, not a manual
- **Direct**: Use "you" and imperative verbs ("Click", "Enter", "Select")
- **Empowering**: Focus on what users CAN do, not limitations
- **Reassuring**: When explaining something complex, acknowledge it

### Writing Guidelines

**Be action-oriented:**
- Good: "To invite a team member, click **Add Member** in your organization settings."
- Avoid: "The Add Member button can be found in the organization settings area."

**Use consistent terminology:**
| Use | Don't Use |
|-----|-----------|
| Organization | Org, team, group |
| Member | User, person, account |
| Plan | Subscription, tier |
| Settings | Preferences, configuration |

**Format instructions clearly:**
1. Number sequential steps
2. Bold UI elements: **Button Name**, **Menu Item**
3. Use `code style` for things users type
4. Use > blockquotes for important notes

**Keep paragraphs short:**
- 2-3 sentences maximum
- One idea per paragraph
- Use bullet points for lists of 3+ items

### Structure Templates

**Feature Overview Page:**
```markdown
# [Feature Name]

[One sentence describing what this feature does and why it's useful.]

## Getting Started

[Prerequisites - what users need before using this feature]

## How to [Primary Action]

1. Step one
2. Step two
3. Step three

## Common Questions

### [Question 1]?
[Answer]

### [Question 2]?
[Answer]
```

**How-To Guide:**
```markdown
# How to [Accomplish Task]

[Brief context - when/why you'd do this]

## Before You Begin

- [Prerequisite 1]
- [Prerequisite 2]

## Steps

1. [First step with specific UI guidance]
2. [Second step]
3. [Third step]

> **Note:** [Any important caveats or tips]

## Next Steps

- [Related action 1]
- [Related action 2]
```

**Troubleshooting Page:**
```markdown
# Troubleshooting [Area]

## [Problem Description]

**Symptoms:** [What the user sees]

**Cause:** [Why this happens, in plain terms]

**Solution:**
1. [Step to fix]
2. [Step to fix]

---

## [Another Problem]
...
```

---

## 3. Product Areas to Document

### MuckRock Accounts Features for End Users

**Account Management**
- Creating an account
- Signing in (password, email link, social login)
- Managing profile (name, avatar, email)
- Two-factor authentication setup
- Password reset and recovery
- Deleting your account

**Organizations**
- Creating an organization
- Organization types and subtypes
- Inviting team members
- Managing member roles and permissions
- Removing members
- Transferring ownership
- Organization settings

**Billing & Plans**
- Available plans and features
- Upgrading or downgrading
- Managing payment methods
- Viewing invoices and receipts
- Non-profit plans
- Canceling subscriptions

**Connected Services**
- Linking MuckRock account
- Linking DocumentCloud account
- Managing connected applications
- OAuth permissions

**Security**
- Two-factor authentication
- Login history
- Session management
- Connected devices

### User Roles Reference
| Role | Capabilities |
|------|--------------|
| Member | Access organization resources |
| Admin | Manage members, settings |
| Owner | Full control, billing, delete org |

---

## 4. Saving and Updating Documentation

### File Organization

Product documentation lives in `docs/product/`:

```
docs/
├── product/                      # User-facing documentation (Markdown)
│   ├── index.md                  # Documentation home/navigation
│   ├── getting-started/
│   │   ├── creating-account.md
│   │   ├── signing-in.md
│   │   └── profile-settings.md
│   ├── organizations/
│   │   ├── creating-organization.md
│   │   ├── inviting-members.md
│   │   ├── managing-roles.md
│   │   └── organization-settings.md
│   ├── billing/
│   │   ├── plans-and-pricing.md
│   │   ├── managing-subscription.md
│   │   └── invoices-and-receipts.md
│   ├── security/
│   │   ├── two-factor-auth.md
│   │   └── login-security.md
│   └── troubleshooting/
│       ├── account-issues.md
│       └── billing-issues.md
└── (existing technical docs)
```

### Creating New Documentation

1. **Choose the right location** based on the topic category
2. **Use kebab-case filenames**: `managing-team-members.md`
3. **Start with the template** from the style section
4. **Update index.md** with a link to the new page

### Updating Existing Documentation

1. **Check if documentation exists** before creating new
2. **Preserve existing structure** when making updates
3. **Note the change** if updating a significant workflow
4. **Review related pages** that might need updates

### Markdown for Notion Compatibility

Notion imports standard Markdown well. Use these elements:

**Supported:**
- Headers (`#`, `##`, `###`)
- Bold (`**text**`) and italic (`*text*`)
- Bullet lists and numbered lists
- Code blocks (```)
- Blockquotes (`>`)
- Links (`[text](url)`)
- Tables
- Horizontal rules (`---`)

**Avoid:**
- HTML tags (use Markdown equivalents)
- Complex nested structures
- Custom shortcodes or extensions

### Screenshot Guidelines

When screenshots are needed:
1. Note the location in the doc: `[Screenshot: Organization settings page]`
2. Use consistent browser/window size
3. Highlight relevant UI elements
4. Avoid showing sensitive data
5. Save screenshots in `docs/product/images/` with descriptive names

### Quality Checklist

Before finalizing documentation:

- [ ] Written from user's perspective, not developer's
- [ ] Uses consistent terminology
- [ ] Steps are numbered and specific
- [ ] UI elements are bolded
- [ ] Prerequisites are clearly stated
- [ ] Common questions addressed
- [ ] No jargon or unexplained technical terms
- [ ] Tested the steps yourself (if possible)
- [ ] Added to index.md
- [ ] Filename is descriptive and kebab-case

---

## Quick Reference

### Common UI Elements in MuckRock Accounts

| Element | How to Reference |
|---------|------------------|
| Main navigation | "Click your profile picture in the top right" |
| Organization switcher | "Select your organization from the dropdown" |
| Settings pages | "Go to **Settings** > **[Section]**" |
| Action buttons | "Click **[Button Text]**" |
| Form fields | "Enter your [field name]" |
| Toggles | "Turn on/off **[Setting Name]**" |

### Standard Phrases

- "If you don't see this option, contact your organization admin."
- "Changes are saved automatically."
- "This action cannot be undone."
- "You'll receive a confirmation email."
- "Need help? Contact support at [support link]."
