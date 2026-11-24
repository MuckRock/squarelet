# How Billing Works

Squarelet sells plans for MuckRock, DocumentCloud and the other client sites,
bills them through Stripe, and tells the client sites what each organization
is entitled to. This page covers the model, why each piece is shaped the way
it is, and where to look in the code. Read the first half for the ideas and
the second half before you change anything.

## Where the code lives

| What | Where |
| --- | --- |
| Billing models: `Plan`, `PlanPrice`, `Subscription`, `SubscriptionItem`, `Customer`, `PaymentMethod`, `Charge`, `Entitlement`, `EntitlementGrant` | `squarelet/organizations/models/payment.py` |
| Stripe invoice mirror | `squarelet/organizations/models/invoice.py` |
| What an organization does: `add_subscription`, `remove_subscription`, `end_subscription`, `save_card`, `charge`, `subscription_cancelled` | `squarelet/organizations/models/organization.py` |
| Starting lines, choosing a price, charges | `squarelet/organizations/querysets.py` (`SubscriptionItemQuerySet`, `ChargeQuerySet`) |
| Legacy plan slug to new tier and price | `squarelet/organizations/plan_mapping.py` |
| Entitlement resource shape and its two formulas | `squarelet/organizations/entitlement_shape.py` |
| Stripe API wrapper and pinned API version | `squarelet/organizations/payments/` (`factory.py`, `base.py`, `providers/stripe_modern.py`, `exceptions.py`) |
| Customer-facing pages | `squarelet/payments/views.py`, `forms.py`; templates in `squarelet/templates/subscriptions/` and `templates/payments/` |
| Per-organization and per-user URL wrappers | `squarelet/organizations/views/subscription.py`, `squarelet/users/views.py` |
| Stripe webhook endpoint | `stripe_webhook` in `squarelet/organizations/views/subscription.py` |
| Webhook handlers and nightly jobs | `squarelet/organizations/tasks.py` |
| Entitlements as the client sites see them | `OrganizationDetailSerializer.get_entitlements` in `squarelet/organizations/serializers.py` |
| Operational commands | `squarelet/organizations/management/commands/` |

## The four objects

| Ours | Stripe | Holds |
| --- | --- | --- |
| `Plan` | Product | What a tier *is*: its name, its entitlements |
| `PlanPrice` | Price | What that tier *costs*, in one variant |
| `Subscription` | Subscription | One billing relationship: an invoice, a period, a payment method |
| `SubscriptionItem` | Subscription item | One line on that invoice |

A plan has many prices, and a subscription has many lines.

A line points at both its `plan` and its `plan_price`. It carries a
`quantity`, and its Stripe item id in `stripe_item_id`. Cancellation state
(`cancelled`, `cancel_at`) belongs to the subscription. A line only reads it
through.

## Three kinds of subscription

Stripe requires every item on a subscription to share a **billing interval**
and a **collection method**. So plans are grouped onto subscriptions, and
every subscription is exactly one `kind`:

| Kind | On Stripe | Lines | One per |
| --- | --- | --- | --- |
| `renewing` | Yes | Any number of renewing paid plans, and their packs | Organization + interval + collection method, while live |
| `one_off` | Yes | One line, set to end at period end from the moment it is bought | Purchase |
| `free` | Never | Any number of free and comped plans | Organization |

`Subscription.kind_for(plan, price)` picks the kind:

- a $0 price gives `free`;
- `Plan.auto_renew=False` gives `one_off`;
- anything else gives `renewing`.

Database constraints on `Subscription` enforce the "one per" column. They
allow one free subscription per organization, and one live (`cancelled=False`)
renewing subscription per interval and collection method.

This means an organization gets one invoice per shape rather than one per
plan: three monthly plans arrive on one bill. A one-off purchase gets its own
invoice when it is bought, and free plans never share a row with paid ones.

**An organization holds a tier once.** Several plan rows can map to the same
tier (see the legacy map below). `add_subscription` refuses a tier the
organization already pays for, and replaces a free line on that tier with the
paid one. A `SubscriptionItem` constraint only stops the same plan appearing
twice on one subscription. The organization-wide rule is enforced in code, not
by the database.

**Buying while cancelling.** Suppose an organization buys a plan while its
subscription of that shape is cancelling. A new subscription starts beside the
old one, and the cancelling one runs out on its own date. Resubscribing the
old one while the new one is live is refused (`LIVE_ON_THE_SAME_BILLING`),
because both would bill the same period.

## Prices

### Prices are immutable

Stripe will not let you change what a Price costs. Changing a tier's price
therefore means **superseding** it (`PlanPrice.supersede(amount)`):

- the old row is marked inactive and keeps pointing at the Stripe Price its
  existing subscribers are billed against;
- a new row becomes the one new subscriptions use.

`PlanPrice.clean` and the admin form lock `amount`, `currency` and `interval`
once a Stripe Price exists.

Nobody is moved automatically. Existing subscribers keep paying what they
signed up for until something deliberately moves them.

### What makes a price distinct

Four fields: `plan`, `interval`, `label`, `code`.

- **`interval`**: monthly or annual.
- **`label`**: `standard`, `nonprofit` or `comped`. An ongoing, structural
  rate class.
- **`code`**: blank for list pricing, or a short slug for an individually
  negotiated deal (`insideclimate`). A negotiated rate may sit *above* list.
  That is why it is a price of its own rather than a discount: Stripe has no
  negative coupon.

The constraint `unique_active_plan_price` allows exactly one *active* price
per combination. Superseded rows accumulate freely.

`amount` is in **cents**. The deprecated `Plan.base_price` is in dollars.

**Permanent discounts are prices; temporary ones are coupons.** A negotiated
rate that lasts is a `code` price. A time-limited promotion is a Stripe
coupon, since coupons support expiry dates and redemption limits.

### Choosing a price for a purchase

`SubscriptionItemQuerySet.resolve_purchase(plan, nonprofit, interval)` works
like this:

1. It looks the plan's slug up in `LEGACY_PLAN_MAP` (`plan_mapping.py`). That
   map says which canonical tier, interval, label and code an old plan row
   now sells as. For example, `sunlight-nonprofit-*` and `*-annual` rows all
   map onto one tier's prices. An unmapped slug defaults to its own plan at
   its own interval, with the `standard` label.
2. An explicit `interval` overrides the mapped one.
3. `nonprofit` swaps a `standard` label for `nonprofit`.
4. It returns the **canonical** plan and its active price. That plan may not
   be the one you passed in. With no price, `start` raises `NotForSale`.

Comped targets are never resolved for a purchase, so a purchase can never be
free.

### Creating prices on Stripe

- `PlanPrice.ensure_stripe_price()` first ensures the Product, then finds or
  creates the Stripe Price.
  - It finds an orphaned Price from an earlier failed attempt by its
    `variant_key`, which is stored in the Price's metadata.
  - A $0 price never reaches Stripe.
- Creating a `Plan` creates its Product and a standard price through signals
  in `organizations/signals.py`.
- Archiving a plan archives its prices and Product.
  - A plan with lines still on it can't be archived.
  - Retired plans are archived, never deleted, because the change log refers
    to them.

## Quantity means two different things

This is the easiest part of the model to get wrong.

- **Legacy group plans** billed `tiered`/`graduated` on Stripe: a flat amount
  up to `minimum_users`, then per block beyond it. Quantity **selected a
  tier**.
- **Every `PlanPrice`** bills a flat `unit_amount`. Quantity **multiplies**.

Reading one as the other overcharges a five-seat subscriber fivefold. The
migration splits a legacy subscription into two lines:

- the base plan at quantity 1;
- a **pack** line carrying the extra blocks.

After that, quantity always multiplies. The deprecated `Plan` fields
`minimum_users`, `base_price` and `price_per_user` stay until every per-user
subscriber has been split this way. Don't zero them early.

## Entitlements

A plan grants entitlements, and an entitlement carries `resources`. Resources
come in pairs: a `base_*` amount and an optional `*_per_user` partner. Keys
with no partner, such as Sunlight research hours, don't scale with quantity.

- Under the old shape, a group got `base + max(quantity - minimum_users, 0) ×
  per_user`.
- Under the new shape, a line grants `base × quantity`.

Packs exist so that the second formula can express the first.

`migrate_entitlement_shape` rewrites resources so that both formulas give the
same number. Its pure functions live in `entitlement_shape.py`.

### How client sites see them

Squarelet does **not** add up an organization's resources. It hands each
client site a list, and the client does the arithmetic.

- `OrganizationDetailSerializer.get_entitlements` returns the entitlements for
  the requesting OAuth client only.
- The list has **one entry per subscription line**, not deduplicated. Each
  entry is `{name, slug, description, resources, update_on, quantity}`, where
  `quantity` is the line's quantity.
- Entitlements from grants (below) follow with `quantity: 1`.
- The list is served by the organization API, by the OIDC `organizations`
  scope and by the user API.
- A parent organization or group with shared resources is not merged in. It
  appears nested under `parent` and `groups` with its own `entitlements`.

`Organization.max_users` is still serialized but deprecated. Purchases don't
update it, so clients should read `quantity`.

`sum_resources` in `payment.py` sums resources for the benefits shown on
plan pages. It is display only.

### Entitlement grants

`EntitlementGrant` gives entitlements outside of any plan, either to listed
organizations or by rule. The rules are `require_verified` and
`require_active_subscription`, restricted by `for_individuals` and
`for_groups`. `EntitlementQuerySet.for_organization` is the union of
plan-derived and grant-derived entitlements.

## Comped access

A comped plan costs nothing and **never reaches Stripe**: no Price, no
subscription item, no invoice.

- Blank Stripe ids on comped rows are correct, not missing data. That is why
  the admin shows a plain dash rather than a link for them.
- Comped and other free plans live on the organization's single `free`
  subscription, never beside paid ones.
- A free line may carry `ends_on`, and it may record why it was granted and
  by whom (`granted_reason`, `granted_by`).
- `ends_on` is the only editable field in the subscription admin. The nightly
  `end_comps` removes lines whose date has passed.

## Buying a plan

The checkout view is `BasePlanCheckout.post` in `payments/views.py`. Its
per-organization and per-user subclasses only resolve the account.

1. **Refusals.**
   - Enterprise plans get "contact us".
   - A tier already paid for is refused.
   - Sunlight plans synced to Wix are capped at `MAX_SUNLIGHT_SUBSCRIPTIONS`.
     The count runs under `select_for_update`, and a full plan joins a
     waitlist.
2. **Payment method.** `card` needs a saved default card. `invoice` is only
   offered on annual prices.
3. **`Organization.add_subscription`** runs atomically and locks the
   organization row. It:
   - saves a new card if one was given;
   - calls `subscription_items.start(...)`;
   - sets `update_on` and `billing_anchor` on the organization's first line;
   - cancels any free line on the same tier;
   - writes a change log and queues the Wix sync.
4. **`SubscriptionItemQuerySet.start`** does the work, in order:
   - Resolves the price and calls `ensure_stripe_price()` before saving
     anything.
   - Chooses the collection method: `send_invoice` only for annual billing
     paid by invoice; everything else charges automatically.
   - Finds or creates the subscription for that kind. A `one_off` always gets
     a new row. A `free` or `renewing` subscription is reused if one of the
     same shape exists.
   - Creates the line.
   - For a new subscription, calls `Subscription.start()`. For an existing
     one, calls `stripe_modify()` and then `settle_added_line()`.
   - Sends the Mailchimp journey and the Slack notice.
5. **`Subscription.start`** creates the Stripe subscription.
   - It sets `cancel_at_period_end` when the subscription doesn't renew.
   - Invoiced subscriptions get `days_until_due=30`.
   - A renewing monthly subscription is anchored to the organization's
     `billing_anchor` day.
   - It caches status and period end, records the Stripe item ids, and checks
     for 3D Secure.

### Proration

`Subscription.proration_behavior` is `always_invoice` for card payers, so an
added line is charged at once. It is `create_prorations` for invoiced
subscriptions, so the charge waits for the next invoice. An anchored first
subscription uses `create_prorations`.

### 3D Secure

Stripe can leave a new subscription `incomplete` with its first invoice
awaiting authentication.

- `_check_3ds_action_required` raises `PaymentActionRequired(client_secret,
  payment_intent_id)`.
- Checkout returns that to the browser as HTTP 402.
- `frontend/views/plan_checkout.ts` runs `stripe.confirmCardPayment` and then
  follows the redirect.

The exception is raised inside `add_subscription`'s transaction, so on master
the local rows roll back while the Stripe subscription remains. Issue #917
tracks this.

One-off charges (`Organization.charge`) have their own confirm step:
`Charge.objects.confirm_payment_intent`.

## Changing, removing and cancelling

Cancellation belongs to the **subscription**, never to a single line, and
mirrors Stripe's own `cancel_at_period_end`. There is no per-line cancellation
state to keep in step.

- **Cancel subscription** (`end_subscription`, `BaseEndSubscription`) ends
  every plan on it at period end, in one step. The billing page shows one
  block per subscription, each with its own Cancel.
- **Cancelling the last paid plan** cancels the subscription at period end.
  The customer keeps what they paid for until then, and nothing is refunded.
- **Removing one plan of several** (`SubscriptionItem.cancel` when
  `removes_now`) takes it off the subscription immediately.
  - Stripe credits the unused time against the next invoice, which exists
    because the other plans keep billing.
  - The removal page shows the credit (`removal_credit`, a Stripe invoice
    preview) before the customer confirms. It signs the preview timestamp, so
    the removal is prorated to the same second the customer was shown.
- **Packs** change by quantity, prorated the same way, and end with their
  base plan.
- **Resubscribe** (`Subscription.uncancel`) un-cancels the whole subscription.
  - It needs a saved payment method.
  - It is refused for one-off purchases.

Stripe has no way to end one item at period end. That is why a plan either
comes off now with a credit, or the whole subscription ends at period end.

**Changing a plan in place** (`SubscriptionItem.modify`, wrapped by
`Organization.modify_subscription`) is for upgrades and downgrades. It never
crosses interval or kind: a paid plan can't become free, or a renewing plan a
one-off, on the same line. Remove the line and add the new one instead. Lines
on a negotiated `code` price can't be modified.

### When a cancelled subscription actually ends

`cancelled=True` with a `cancel_at` date means "stop then". The row goes away
in one of two ways:

- Stripe sends `customer.subscription.deleted`, and the handler retires it.
- The nightly sweep in `restore_organization` catches any the webhook missed,
  the day after `cancel_at`.

Retiring (`retire_subscription`) deletes the paid lines and keeps any free
ones, minus the Stripe ids. `cancelled=True` with **no** date means "remove
tonight". Write the pair only through `Cancellable.mark_cancelled` and
`clear_cancellation`.

## Payment methods, charges and invoices

- **`Customer`**: one per organization. `stripe_customer` creates the Stripe
  customer on first use, under a row lock. If Stripe has lost the stored id,
  it clears it.
- **`PaymentMethod`**: a local cache of the saved cards (brand, last4,
  expiry, default). Pages read the cache. The `payment_method.*` and
  `customer.updated` webhooks keep it current.
- **Saving a card** (`Organization.save_card`): creates a `pm_`, attaches it,
  makes it the invoice default and clears `payment_failed`. Legacy `card_`
  and `src_` sources are still read.
- **`Charge`**: one row per Stripe charge.
  - It is created both by `Charge.objects.make_charge` and by the
    `charge.succeeded` webhook, with `get_or_create` because the two race.
  - `download_receipt_pdf` stores Stripe's receipt as a PDF.
- **`Invoice`**: a mirror of Stripe invoices, kept current by the
  `invoice.*` webhooks. In the admin, "mark as paid" records a check or bank
  transfer on Stripe (`paid_out_of_band`).
- **`ReceiptEmail`**: the address receipts go to, one per organization. Its
  setter also updates the Stripe customer's email.

## Stripe talking to us: webhooks

The endpoint is `/organizations/~stripe_webhook/`. It verifies the signature
against `STRIPE_WEBHOOK_SECRET`, then hands `data.object` to a Celery task.
Unknown event types get a 200.

| Event | Handler | Does |
| --- | --- | --- |
| `charge.succeeded` | `handle_charge_succeeded` | Records the `Charge` and queues the receipt PDF. Retries while the organization is missing. Skips MuckRock donations and crowdfunds. |
| `invoice.created` | `handle_invoice_created` | Records the `Invoice` and copies organization and plan metadata onto it in Stripe. |
| `invoice.updated` / `finalized` / `paid` / `marked_uncollectible` / `voided` | `handle_invoice_*` | Update the `Invoice`. `paid` clears `payment_failed`. |
| `invoice.payment_failed` | `handle_invoice_failed` | Sets `payment_failed` and emails the admins. The fourth attempt cancels the subscription. |
| `customer.updated`, `payment_method.*` | `handle_customer_updated`, `handle_payment_method_*` | Keep `PaymentMethod` in step. |
| `customer.subscription.updated` | `handle_subscription_updated` | Caches status and period. Mirrors `cancel_at_period_end`. Status `canceled` retires the subscription. |
| `customer.subscription.deleted` | `handle_subscription_deleted` | Retires the subscription. |

Nothing deduplicates on event id. Handlers are written to be safe to repeat:
`get_or_create`, update-or-create, and a lookup that misses logs and returns.
An event for a subscription we have no row for is logged as unknown.

## Scheduled jobs and failed payments

Celery beat (`CELERY_BEAT_SCHEDULE` in `config/settings/base.py`) runs two
billing jobs.

- **`restore_organization`**, daily at 00:05, makes no Stripe calls. It:
  - retires cancelled subscriptions whose date has passed;
  - runs `end_comps`;
  - moves each due organization's `update_on` (its monthly resource reset
    day) forward a month, or clears it when nothing is left;
  - sends one cache invalidation for everything it touched.
- **`check_overdue_invoices`**, daily at 02:00, handles invoiced customers.
  - During `OVERDUE_INVOICE_GRACE_PERIOD_DAYS` (default 30), it sets
    `payment_failed` and sends reminders.
  - After the grace period, it cancels the subscription
    (`Organization.subscription_cancelled`), marks the invoice uncollectible
    and emails the customer.

Card failures follow Stripe's retry schedule instead. Each failure emails the
admins, and the fourth cancels the subscription.

`subscription_cancelled` deletes the Stripe subscription and the local row at
once. It does not wait for period end, because nothing was paid for the
period.

## Telling the client sites

Squarelet never pushes entitlement data. It tells a client site *that* an
organization changed, and the client fetches the organization again.

- `send_cache_invalidations("organization", uuids)` POSTs a signed
  `{type, uuids, timestamp, signature}` to every `ClientProfile.webhook_url`.
- Within a request, the calls are batched by middleware. In Celery or a shell
  they go out at once.

It fires on:

- every `Organization.save()`, including a change to `payment_failed`;
- saving or removing a card;
- removing a plan;
- the webhook cancel path;
- the nightly sweep;
- any change to an `EntitlementGrant`.

It does **not** fire when an `Entitlement`'s `resources` change. Send one by
hand after editing resources if clients must see the change before their
cache expires.

`ENABLE_SEND_CACHE_INVALIDATIONS` turns all of this off.

## Who is the source of truth

Stripe and Squarelet each own different facts:

- **Stripe owns money.** What was charged, when the period ends, how payment
  is collected, whether a subscription is set to end.
- **We own meaning.** Which plan a line is, what it grants, whether a price is
  the current list rate, who was comped and why.

Local copies of Stripe's facts are a **cache**:

- the cache is `Subscription.STRIPE_CACHED_FIELDS`, plus `cancelled` and
  `cancel_at`;
- it is refreshed from Stripe on any interaction and by webhooks;
- `audit_subscriptions` reconciles it with Stripe.

Where the two disagree, Stripe wins.

### Stripe API details

- The API version is pinned in code, not settings:
  `CURRENT_API_VERSION` in `payments/providers/stripe_modern.py`.
  - Building the provider sets `stripe.api_version` globally.
  - Upgrade the version and the SDK together, then run the sandbox tests.
- Always go through `get_payment_provider()` rather than calling `stripe.*`
  directly, so the version and the error translation apply.
  - The error translation turns Stripe errors into `SubscriptionError`,
    `CardError` and so on, from `payments/exceptions.py`.
  - Some older code and `audit_subscriptions` still call `stripe.*`
    directly.
- Under the pinned version, `current_period_end` lives on the subscription
  *items*. Read it with `get_current_period_end`.
- Read `stripe_sub["items"]` with brackets. Attribute access finds the dict's
  `items` method.
- Every item sent to `Subscription.modify` must carry its id. An item without
  one is added as a new line. That is why `sync_stripe_item_ids` runs before
  every modify.

## Operating it

### Settings

- `STRIPE_PUB_KEY`, `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` are
  required in deployed environments.
- With no webhook secret, the endpoint skips signature verification. Tests
  rely on that.
- `STRIPE_SANDBOX_SECRET_KEY` is used only by the sandbox tests.
- `MAX_SUNLIGHT_SUBSCRIPTIONS` and `OVERDUE_INVOICE_GRACE_PERIOD_DAYS` are the
  other billing settings.

### Management commands

All of these are in `squarelet/organizations/management/commands/`. Each is
safe to re-run.

| Command | What it does | Flags |
| --- | --- | --- |
| `audit_subscriptions` | Read-only report of drift between local subscriptions or lines and Stripe: missing on either side, status, cancellation, period end, quantity, price | `--org`, `--show-ok`, `--stripe-orphans` |
| `sync_subscriptions` | Copies `STRIPE_CACHED_FIELDS` from Stripe onto every subscription with a Stripe id | `--org`, `--dry-run` |
| `backfill_stripe_item_ids` | Fills missing `stripe_item_id` values and cached period/status | `--org`, `--dry-run` |
| `consolidate_stripe_products` | Creates the Products, Prices and `PlanPrice` rows in its hard-coded `PRICE_MATRIX`. Deliberately not one transaction, so a re-run finishes a partial one. | `--dry-run`, `--allow-missing` (dev and staging) |
| `migrate_entitlement_shape` | Rewrites entitlement resources to the `base × quantity` shape. Refuses if any grant would change. | `--dry-run` |
| `archive_legacy_plans` | Archives plans that aren't canonical, have no lines and can't be bought | `--dry-run` |
| `cleanup_bad_receipt_pdfs` | Replaces stored receipts that aren't really PDFs | `--org`, `--dry-run` |

Start with `audit_subscriptions` when something looks wrong.

### Admin

- **Subscription**: read-only, except for a comped line's `ends_on`.
- **Plan**: inline prices are pushed to Stripe on save.
- **PlanPrice**: locks the Stripe-bound fields. To change a price, add a row
  and deactivate the old one.
- **Invoice**: has "mark as paid".
- **Charge**: exports to CSV.

## Testing

- `pytest.ini` deselects `-m stripe`. Ordinary tests use fake keys and mock
  Stripe, usually by patching `get_payment_provider`, a model method or a
  `stripe.*` call.
- Factories are in `squarelet/organizations/tests/factories.py`.
  - `SubscriptionItemFactory` gives every line a price.
  - `SubscriptionFactory` reuses a subscription of the same shape, as the
    real code does.
- **Sandbox tests** in `squarelet/organizations/tests/test_stripe_sandbox.py`
  talk to a real Stripe sandbox (`inv test-stripe`, i.e. `pytest -m
  stripe`).
  - They need `STRIPE_SANDBOX_SECRET_KEY`, and refuse a live key.
  - They clean up after themselves.
  - Run them whenever you change how we call Stripe. Mocks have hidden real
    bugs here before, such as item ids never being written.
- Webhook handler tests are in `squarelet/organizations/tests/test_tasks.py`,
  one class per handler. The endpoint itself is `TestStripeWebhook` in
  `test_views.py`.

## Easy to get wrong

- `Plan.free` reads the deprecated dollar fields. A line's `is_free` reads
  `PlanPrice.amount`, in cents.
- `resolve_purchase` returns the canonical plan, not the one you asked for.
- `supersede` changes nobody's bill.
- The entitlement list repeats an entitlement once per line, and again if a
  grant also gives it. Clients must expect duplicates.
- `has_active_subscription()` counts free and comped lines too.
- A card subscription is charged immediately for an added line
  (`always_invoice`), so adding a plan can trigger 3D Secure as well.
- `cancel_at` is a local date, while Stripe's `cancel_at` is a timestamp.
  `mark_cancelled` converts it with `localtime`, so a period ending late in
  the UTC day lands on the right date.
- The fourth failed card attempt cancels the subscription. This is
  hard-coded in `handle_invoice_failed` and separate from the invoice grace
  period.

## Open questions

- **Per-organization access is attached to the plan, not the price.** Nothing
  self-serve can reach a `code` price: a customer picks a plan, and the price
  is derived from it.
  - A negotiated deal has its own non-public `Plan`, offered only to the
    organizations in `private_organizations`. So the restriction already
    exists, one level up.
  - It stops working once negotiated deals collapse onto shared canonical
    tiers, because then everyone has the plan and the difference lives in
    the price.
  - A price-to-organization relation is therefore needed by the plan-collapse
    step.
- **Discounts are not modelled.** No coupon, promo code or discount is stored
  locally. `audit_subscriptions` reports any discount as drift, so the first
  real coupon makes the drift report noisy unless it lands with that change.
- **Stripe as a staff UI is undecided.** Prices created in the Stripe console
  are invisible to us.
  - Adopting them needs a webhook, and a rule for the fields Stripe has no
    opinion about (`label`, `code`).
  - The more urgent case is a price *archived* in the console while we still
    believe it is sellable.
  - We could require that metadata to be entered in Stripe. Creating prices
    in the Django admin gives a better form for the required fields.
